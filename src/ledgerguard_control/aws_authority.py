"""DynamoDB registration, fencing, failure and fixed-size publication authority.

The adapter uses only conditional operations and strongly consistent reads.  Its
request tests are not a live AWS persistence or effective-permission receipt.
"""

from __future__ import annotations

import re
from typing import Any

from ledgerguard.stage3.canonical import canonical_digest

from .authority import Attempt, _attempt, _digest, _id, publication_transaction
from .contracts import ControlRejected, strict_json


class DynamoDBAuthority:
    def __init__(self, client: Any, table: str):
        if re.fullmatch(r"ledgerguard-[a-z0-9-]+-control", table) is None:
            raise ControlRejected("invalid control table")
        self.client = client
        self.table = table

    @staticmethod
    def _conditional(error: Exception) -> bool:
        response = getattr(error, "response", None)
        if type(response) is not dict:
            return False
        detail = response.get("Error")
        return type(detail) is dict and detail.get("Code") in {
            "ConditionalCheckFailedException",
            "TransactionCanceledException",
        }

    @staticmethod
    def _s(item: dict[str, Any], name: str) -> str:
        value = item.get(name)
        if type(value) is not dict or set(value) != {"S"} or type(value["S"]) is not str:
            raise ControlRejected("invalid DynamoDB string attribute")
        return value["S"]

    @staticmethod
    def _n(item: dict[str, Any], name: str) -> int:
        value = item.get(name)
        if (
            type(value) is not dict
            or set(value) != {"N"}
            or type(value["N"]) is not str
            or re.fullmatch(r"[1-9][0-9]{0,18}", value["N"]) is None
        ):
            raise ControlRejected("invalid DynamoDB integer attribute")
        result = int(value["N"])
        if result > 2**63 - 1:
            raise ControlRejected("DynamoDB fence exceeds bound")
        return result

    def _get(self, pk: str, sk: str) -> dict[str, Any] | None:
        response = self.client.get_item(
            TableName=self.table,
            Key={"pk": {"S": pk}, "sk": {"S": sk}},
            ConsistentRead=True,
        )
        if type(response) is not dict:
            raise ControlRejected("invalid DynamoDB get response")
        item = response.get("Item")
        if item is None:
            return None
        if type(item) is not dict:
            raise ControlRejected("invalid DynamoDB item")
        return item

    def _registration(self, namespace: str, run_id: str, identity: str) -> dict[str, Any]:
        item = self._get(f"RUN#{run_id}", "REGISTRATION")
        if item is None:
            raise ControlRejected("run registration is missing")
        if (
            self._s(item, "pk") != f"RUN#{run_id}"
            or self._s(item, "sk") != "REGISTRATION"
            or self._s(item, "namespace") != namespace
            or self._s(item, "identity") != identity
        ):
            raise ControlRejected("immutable run identity conflict")
        return item

    def register(self, namespace: str, run_id: str, identity: str) -> str | None:
        _id(namespace)
        _id(run_id)
        _digest(identity)
        item = {
            "pk": {"S": f"RUN#{run_id}"},
            "sk": {"S": "REGISTRATION"},
            "namespace": {"S": namespace},
            "identity": {"S": identity},
            "status": {"S": "REGISTERED"},
        }
        try:
            self.client.put_item(
                TableName=self.table,
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
            return None
        except Exception as error:
            if not self._conditional(error):
                raise
        existing = self._registration(namespace, run_id, identity)
        status = self._s(existing, "status")
        if status == "REGISTERED":
            return None
        if status != "COMMITTED":
            raise ControlRejected("run registration status differs")
        commit = self._s(existing, "commit")
        self._require_reachable(namespace, commit, run_id, identity)
        return commit

    def _replay_attempt(
        self, namespace: str, run_id: str, identity: str, attempt_id: str, owner: str
    ) -> Attempt:
        item = self._get(f"RUN#{run_id}", f"ATTEMPT#{attempt_id}")
        if item is None:
            raise ControlRejected("attempt admission failed")
        attempt = Attempt(
            namespace=self._s(item, "namespace"),
            run_id=run_id,
            identity_sha256=self._s(item, "identity"),
            attempt_id=attempt_id,
            owner=self._s(item, "owner"),
            fence=self._n(item, "fence"),
        )
        if (
            attempt != Attempt(namespace, run_id, identity, attempt_id, owner, attempt.fence)
            or self._s(item, "status") != "ACTIVE"
        ):
            raise ControlRejected("attempt identity reuse or stale ownership")
        run = self._registration(namespace, run_id, identity)
        if (
            self._s(run, "status") != "REGISTERED"
            or self._s(run, "active_attempt") != attempt_id
            or self._s(run, "owner") != owner
            or self._n(run, "fence") != attempt.fence
        ):
            raise ControlRejected("attempt is not the active fenced owner")
        return attempt

    def admit(
        self, namespace: str, run_id: str, identity: str, attempt_id: str, owner: str
    ) -> Attempt:
        probe = Attempt(namespace, run_id, identity, attempt_id, owner, 1)
        _attempt(probe)
        if self._get(f"RUN#{run_id}", f"ATTEMPT#{attempt_id}") is not None:
            return self._replay_attempt(namespace, run_id, identity, attempt_id, owner)
        counter = self.client.update_item(
            TableName=self.table,
            Key={"pk": {"S": f"NAMESPACE#{namespace}"}, "sk": {"S": "FENCE"}},
            UpdateExpression="ADD #next :one",
            ExpressionAttributeNames={"#next": "next_fence"},
            ExpressionAttributeValues={":one": {"N": "1"}},
            ReturnValues="UPDATED_NEW",
        )
        if type(counter) is not dict or type(counter.get("Attributes")) is not dict:
            raise ControlRejected("fence allocation response differs")
        fence = self._n(counter["Attributes"], "next_fence")
        attempt = Attempt(namespace, run_id, identity, attempt_id, owner, fence)
        try:
            self.client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self.table,
                            "Item": {
                                "pk": {"S": f"RUN#{run_id}"},
                                "sk": {"S": f"ATTEMPT#{attempt_id}"},
                                "namespace": {"S": namespace},
                                "identity": {"S": identity},
                                "owner": {"S": owner},
                                "fence": {"N": str(fence)},
                                "status": {"S": "ACTIVE"},
                            },
                            "ConditionExpression": "attribute_not_exists(pk)",
                        }
                    },
                    {
                        "Update": {
                            "TableName": self.table,
                            "Key": {"pk": {"S": f"RUN#{run_id}"}, "sk": {"S": "REGISTRATION"}},
                            "UpdateExpression": "SET #attempt=:attempt,#owner=:owner,#fence=:fence",
                            "ConditionExpression": "#namespace=:namespace AND #identity=:identity "
                            "AND #status=:registered AND attribute_not_exists(#attempt)",
                            "ExpressionAttributeNames": {
                                "#namespace": "namespace",
                                "#identity": "identity",
                                "#status": "status",
                                "#attempt": "active_attempt",
                                "#owner": "owner",
                                "#fence": "fence",
                            },
                            "ExpressionAttributeValues": {
                                ":namespace": {"S": namespace},
                                ":identity": {"S": identity},
                                ":registered": {"S": "REGISTERED"},
                                ":attempt": {"S": attempt_id},
                                ":owner": {"S": owner},
                                ":fence": {"N": str(fence)},
                            },
                        }
                    },
                ]
            )
            return attempt
        except Exception as error:
            try:
                return self._replay_attempt(namespace, run_id, identity, attempt_id, owner)
            except Exception:
                raise ControlRejected("attempt admission failed or conflicted") from error

    def fail(self, attempt: Attempt) -> None:
        _attempt(attempt)
        request = {
            "TransactItems": [
                {
                    "Update": {
                        "TableName": self.table,
                        "Key": {
                            "pk": {"S": f"RUN#{attempt.run_id}"},
                            "sk": {"S": f"ATTEMPT#{attempt.attempt_id}"},
                        },
                        "UpdateExpression": "SET #status=:failed",
                        "ConditionExpression": (
                            "#status=:active AND #owner=:owner AND #fence=:fence"
                        ),
                        "ExpressionAttributeNames": {
                            "#status": "status",
                            "#owner": "owner",
                            "#fence": "fence",
                        },
                        "ExpressionAttributeValues": {
                            ":active": {"S": "ACTIVE"},
                            ":failed": {"S": "FAILED"},
                            ":owner": {"S": attempt.owner},
                            ":fence": {"N": str(attempt.fence)},
                        },
                    }
                },
                {
                    "Update": {
                        "TableName": self.table,
                        "Key": {"pk": {"S": f"RUN#{attempt.run_id}"}, "sk": {"S": "REGISTRATION"}},
                        "UpdateExpression": "REMOVE #attempt,#owner,#fence",
                        "ConditionExpression": (
                            "#namespace=:namespace AND #identity=:identity "
                            "AND #status=:registered AND #attempt=:attempt "
                            "AND #owner=:owner AND #fence=:fence"
                        ),
                        "ExpressionAttributeNames": {
                            "#namespace": "namespace",
                            "#identity": "identity",
                            "#status": "status",
                            "#attempt": "active_attempt",
                            "#owner": "owner",
                            "#fence": "fence",
                        },
                        "ExpressionAttributeValues": {
                            ":namespace": {"S": attempt.namespace},
                            ":identity": {"S": attempt.identity_sha256},
                            ":registered": {"S": "REGISTERED"},
                            ":attempt": {"S": attempt.attempt_id},
                            ":owner": {"S": attempt.owner},
                            ":fence": {"N": str(attempt.fence)},
                        },
                    }
                },
            ]
        }
        try:
            self.client.transact_write_items(**request)
        except Exception as error:
            try:
                token = self._get(
                    f"RUN#{attempt.run_id}", f"ATTEMPT#{attempt.attempt_id}"
                )
                run = self._registration(
                    attempt.namespace, attempt.run_id, attempt.identity_sha256
                )
                if (
                    token is None
                    or self._s(token, "namespace") != attempt.namespace
                    or self._s(token, "identity") != attempt.identity_sha256
                    or self._s(token, "owner") != attempt.owner
                    or self._n(token, "fence") != attempt.fence
                    or self._s(token, "status") != "FAILED"
                    or self._s(run, "status") != "REGISTERED"
                    or any(name in run for name in ("active_attempt", "owner", "fence"))
                ):
                    raise ControlRejected("failed attempt postcondition differs")
                return
            except Exception:
                raise ControlRejected(
                    "attempt failure was not durably recorded"
                ) from error

    def _commit(self, namespace: str, digest: str) -> dict[str, Any]:
        _id(namespace)
        _digest(digest)
        item = self._get(f"NAMESPACE#{namespace}", f"COMMIT#{digest}")
        if item is None:
            raise ControlRejected("authoritative commit is missing")
        value = strict_json(self._s(item, "document").encode())
        if canonical_digest(value) != digest or value.get("namespace") != namespace:
            raise ControlRejected("authoritative commit integrity mismatch")
        return value

    def _require_reachable(
        self, namespace: str, digest: str, run_id: str | None = None, identity: str | None = None
    ) -> None:
        root = self._get(f"NAMESPACE#{namespace}", "ROOT")
        if root is None:
            raise ControlRejected("namespace root is missing")
        head: Any = self._s(root, "head")
        seen: set[str] = set()
        for _ in range(1024):
            if head in seen:
                raise ControlRejected("commit ancestry cycle")
            seen.add(head)
            value = self._commit(namespace, head)
            if head == digest:
                if (run_id is not None and value.get("run_id") != run_id) or (
                    identity is not None and value.get("identity_sha256") != identity
                ):
                    raise ControlRejected("terminal run points at another identity")
                return
            head = value.get("predecessor")
            if head is None:
                break
            _digest(head)
        raise ControlRejected("commit is not reachable from authoritative root")

    def read_root(self, namespace: str) -> dict[str, Any] | None:
        _id(namespace)
        root = self._get(f"NAMESPACE#{namespace}", "ROOT")
        if root is None:
            return None
        return self._commit(namespace, self._s(root, "head"))

    def publish(self, attempt: Attempt, predecessor: str | None, preparation_sha256: str) -> str:
        request = publication_transaction(self.table, attempt, predecessor, preparation_sha256)
        document = strict_json(
            request["TransactItems"][1]["Put"]["Item"]["document"]["S"].encode()
        )
        digest = canonical_digest(document)
        try:
            self.client.transact_write_items(**request)
            return digest
        except Exception as error:
            try:
                self._require_reachable(
                    attempt.namespace, digest, attempt.run_id, attempt.identity_sha256
                )
                run = self._registration(
                    attempt.namespace, attempt.run_id, attempt.identity_sha256
                )
                if self._s(run, "status") != "COMMITTED" or self._s(run, "commit") != digest:
                    raise ControlRejected("run terminal authority differs")
                return digest
            except Exception:
                raise ControlRejected(
                    "publication failed and exact commit is not authoritative"
                ) from error
