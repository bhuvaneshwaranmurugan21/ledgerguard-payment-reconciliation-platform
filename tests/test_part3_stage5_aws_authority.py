"""AWS authority transport contracts; these tests make no AWS call."""

from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from typing import Any

import pytest

from ledgerguard_control.aws_authority import DynamoDBAuthority
from ledgerguard_control.aws_objects import S3ImmutableObjects
from ledgerguard_control.contracts import ControlRejected

OWNER = (
    "arn:aws:states:ap-southeast-2:857229544428:execution:ledgerguard-test:execution-one"
)


class ServiceError(Exception):
    def __init__(self, code: str):
        self.response = {"Error": {"Code": code}}


class S3:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.bodies: dict[str, bytes] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.bad_response: dict[str, Any] | None = None

    def put_object(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("put_object", request))
        key = request["Key"]
        if self.rows:
            raise ServiceError("PreconditionFailed")
        version = "version-one"
        self.rows.append(
            {"Key": key, "VersionId": version, "Size": len(request["Body"]), "IsLatest": True}
        )
        self.bodies[version] = request["Body"]
        if self.bad_response is not None:
            return self.bad_response
        return {"VersionId": version, "ChecksumSHA256": request["ChecksumSHA256"]}

    def list_object_versions(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("list_object_versions", request))
        versions = [deepcopy(row) for row in self.rows if not row.get("DeleteMarker")]
        deleted = [
            {
                key: deepcopy(value)
                for key, value in row.items()
                if key not in {"Size", "DeleteMarker"}
            }
            for row in self.rows
            if row.get("DeleteMarker")
        ]
        return {"Versions": versions, "DeleteMarkers": deleted, "IsTruncated": False}

    def get_object(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("get_object", request))
        raw = self.bodies[request["VersionId"]]
        return {
            "Body": BytesIO(raw),
            "VersionId": request["VersionId"],
            "ContentLength": len(raw),
        }


def test_s3_create_or_verify_is_checksum_bound_and_detects_history() -> None:
    client = S3()
    store = S3ImmutableObjects(client, "bucket-one")
    uri = "s3://bucket-one/publications/run/value.json"
    assert store.put_immutable(uri, b"{}\n") == "version-one"
    assert store.put_immutable(uri, b"{}\n") == "version-one"
    put = client.calls[0][1]
    assert put["IfNoneMatch"] == "*" and put["ChecksumAlgorithm"] == "SHA256"
    client.rows[0]["IsLatest"] = False
    client.rows.append(
        {"Key": put["Key"], "VersionId": "version-two", "Size": 3, "IsLatest": True}
    )
    client.bodies["version-two"] = b"{}\n"
    with pytest.raises(ControlRejected, match="history"):
        store.put_immutable(uri, b"{}\n")


@pytest.mark.parametrize("change", [{"Size": 99}, {"DeleteMarker": True}])
def test_s3_replay_rejects_changed_size_or_delete_marker(change: dict[str, Any]) -> None:
    client = S3()
    store = S3ImmutableObjects(client, "bucket-one")
    uri = "s3://bucket-one/publications/a"
    store.put_immutable(uri, b"x")
    client.rows[0].update(change)
    if change.get("DeleteMarker"):
        client.rows[0].pop("Size")
    with pytest.raises(ControlRejected, match="history"):
        store.put_immutable(uri, b"x")


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"VersionId": None, "ChecksumSHA256": "x"},
        {"VersionId": "null", "ChecksumSHA256": "x"},
        {"VersionId": "version-one", "ChecksumSHA256": "wrong"},
    ],
)
def test_s3_put_requires_exact_version_and_checksum(response: dict[str, Any]) -> None:
    client = S3()
    client.bad_response = response
    with pytest.raises(ControlRejected, match="response"):
        S3ImmutableObjects(client, "bucket-one").put_immutable(
            "s3://bucket-one/publications/a", b"x"
        )


def test_s3_non_precondition_error_and_changed_bytes_propagate_or_reject() -> None:
    class Denied(S3):
        def put_object(self, **request: Any) -> dict[str, Any]:
            raise ServiceError("AccessDenied")

    with pytest.raises(ServiceError):
        S3ImmutableObjects(Denied(), "bucket-one").put_immutable(
            "s3://bucket-one/publications/a", b"x"
        )
    assert not S3ImmutableObjects._precondition_failed(Exception("plain"))

    client = S3()
    store = S3ImmutableObjects(client, "bucket-one")
    uri = "s3://bucket-one/publications/a"
    store.put_immutable(uri, b"x")
    client.bodies["version-one"] = b"y"
    with pytest.raises(ControlRejected, match="bytes"):
        store.put_immutable(uri, b"x")


@pytest.mark.parametrize(
    "page",
    [
        [],
        {},
        {"IsTruncated": "false"},
        {"IsTruncated": False, "Versions": {}},
        {
            "IsTruncated": False,
            "Versions": [
                {"Key": "publications/a", "VersionId": None, "Size": 1, "IsLatest": True}
            ],
        },
        {
            "IsTruncated": False,
            "Versions": [
                {"Key": "publications/a", "VersionId": "v", "Size": -1, "IsLatest": True}
            ],
        },
    ],
)
def test_s3_exact_history_rejects_malformed_pages(page: Any) -> None:
    class Page(S3):
        def list_object_versions(self, **request: Any) -> Any:
            return page

    with pytest.raises(ControlRejected):
        S3ImmutableObjects(Page(), "bucket-one")._exact_history("publications/a")


def test_s3_exact_history_paginates_and_bounds_versions_and_tokens() -> None:
    row = {"Key": "publications/a", "VersionId": "v", "Size": 1, "IsLatest": True}

    class Pages(S3):
        def __init__(self, pages: list[dict[str, Any]]):
            super().__init__()
            self.pages = iter(pages)

        def list_object_versions(self, **request: Any) -> dict[str, Any]:
            return next(self.pages)

    pages = Pages(
        [
            {
                "IsTruncated": True,
                "Versions": [{**row, "Key": "publications/another"}],
                "NextKeyMarker": "publications/a",
                "NextVersionIdMarker": "v",
            },
            {"IsTruncated": False, "Versions": [row]},
        ]
    )
    assert len(S3ImmutableObjects(pages, "bucket-one")._exact_history("publications/a")) == 1
    repeated = {
        "IsTruncated": True,
        "NextKeyMarker": "publications/a",
        "NextVersionIdMarker": "v",
    }
    with pytest.raises(ControlRejected, match="continuation"):
        S3ImmutableObjects(Pages([repeated, repeated]), "bucket-one")._exact_history(
            "publications/a"
        )
    with pytest.raises(ControlRejected, match="continuation"):
        S3ImmutableObjects(
            Pages([{"IsTruncated": True, "NextKeyMarker": None, "NextVersionIdMarker": "v"}]),
            "bucket-one",
        )._exact_history("publications/a")
    too_many = [{**row, "VersionId": f"v{i}", "IsLatest": i == 16} for i in range(17)]
    with pytest.raises(ControlRejected, match="history exceeds"):
        S3ImmutableObjects(
            Pages([{"IsTruncated": False, "Versions": too_many}]), "bucket-one"
        )._exact_history("publications/a")
    endless = [
        {
            "IsTruncated": True,
            "NextKeyMarker": f"publications/a-{i}",
            "NextVersionIdMarker": f"v{i}",
        }
        for i in range(16)
    ]
    with pytest.raises(ControlRejected, match="pagination exceeds"):
        S3ImmutableObjects(Pages(endless), "bucket-one")._exact_history("publications/a")


@pytest.mark.parametrize(
    ("bucket", "uri", "raw"),
    [
        ("bad/path", "s3://bad/path/publications/a", b"x"),
        ("bucket-one", "s3://bucket-two/publications/a", b"x"),
        ("bucket-one", "s3://bucket-one/runs/a", b"x"),
        ("bucket-one", "s3://bucket-one/publications/a", b""),
        ("bucket-one", "s3://bucket-one/publications/a", b"x" * 131073),
    ],
)
def test_s3_immutable_address_and_body_are_closed(bucket: str, uri: str, raw: bytes) -> None:
    client = S3()
    if bucket == "bad/path":
        with pytest.raises(ControlRejected):
            S3ImmutableObjects(client, bucket)
    else:
        with pytest.raises(ControlRejected):
            S3ImmutableObjects(client, bucket).put_immutable(uri, raw)
    assert client.calls == []


class Dynamo:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}
        self.next_fence = 0
        self.raise_after: str | None = None
        self.calls: list[tuple[str, dict[str, Any]]] = []

    @staticmethod
    def key(item: dict[str, Any]) -> tuple[str, str]:
        return item["pk"]["S"], item["sk"]["S"]

    def put_item(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("put_item", deepcopy(request)))
        key = self.key(request["Item"])
        if key in self.items:
            raise ServiceError("ConditionalCheckFailedException")
        self.items[key] = deepcopy(request["Item"])
        return {}

    def get_item(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("get_item", deepcopy(request)))
        item = self.items.get(self.key(request["Key"]))
        return {} if item is None else {"Item": deepcopy(item)}

    def update_item(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("update_item", deepcopy(request)))
        self.next_fence += 1
        return {"Attributes": {"next_fence": {"N": str(self.next_fence)}}}

    def transact_write_items(self, **request: Any) -> dict[str, Any]:
        self.calls.append(("transact_write_items", deepcopy(request)))
        operations = request["TransactItems"]
        if len(operations) == 2 and "Put" in operations[0]:
            put = operations[0]["Put"]["Item"]
            run_update = operations[1]["Update"]
            run = self.items.get(self.key(run_update["Key"]))
            if run is None or "active_attempt" in run or self.key(put) in self.items:
                raise ServiceError("TransactionCanceledException")
            values = run_update["ExpressionAttributeValues"]
            if (
                run["namespace"] != values[":namespace"]
                or run["identity"] != values[":identity"]
                or run["status"] != values[":registered"]
            ):
                raise ServiceError("TransactionCanceledException")
            self.items[self.key(put)] = deepcopy(put)
            run["active_attempt"] = values[":attempt"]
            run["owner"] = values[":owner"]
            run["fence"] = values[":fence"]
        elif len(operations) == 2:
            attempt_update, run_update = (item["Update"] for item in operations)
            attempt = self.items[self.key(attempt_update["Key"])]
            run = self.items[self.key(run_update["Key"])]
            attempt["status"] = {"S": "FAILED"}
            for name in ("active_attempt", "owner", "fence"):
                run.pop(name)
        else:
            root_update, commit_put, run_update, attempt_update = operations
            root = self.items.get(self.key(root_update["Update"]["Key"]))
            root_values = root_update["Update"]["ExpressionAttributeValues"]
            if root is None:
                if ":previous" in root_values:
                    raise ServiceError("TransactionCanceledException")
                root = deepcopy(root_update["Update"]["Key"])
                self.items[self.key(root)] = root
            elif root.get("head") != root_values.get(":previous"):
                raise ServiceError("TransactionCanceledException")
            commit = commit_put["Put"]["Item"]
            if self.key(commit) in self.items:
                raise ServiceError("TransactionCanceledException")
            run = self.items[self.key(run_update["Update"]["Key"])]
            attempt = self.items[self.key(attempt_update["Update"]["Key"])]
            root["head"] = root_values[":commit"]
            self.items[self.key(commit)] = deepcopy(commit)
            run["status"] = {"S": "COMMITTED"}
            run["commit"] = root_values[":commit"]
            attempt["status"] = {"S": "COMMITTED"}
        if self.raise_after is not None:
            code, self.raise_after = self.raise_after, None
            raise ServiceError(code)
        return {}


def test_dynamodb_full_lifecycle_replay_failure_and_ambiguous_publication() -> None:
    client = Dynamo()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    assert store.register("namespace-one", "run-first", "a" * 64) is None
    assert store.register("namespace-one", "run-first", "a" * 64) is None
    attempt = store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)
    assert attempt.fence == 1
    assert store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER) == attempt
    store.fail(attempt)
    second = store.admit("namespace-one", "run-first", "a" * 64, "attempt-two", OWNER)
    assert second.fence == 2
    client.raise_after = "ServiceUnavailable"
    commit = store.publish(second, None, "b" * 64)
    assert store.register("namespace-one", "run-first", "a" * 64) == commit
    assert store.read_root("namespace-one")["preparation_sha256"] == "b" * 64
    assert all(
        request.get("ConsistentRead") is True
        for name, request in client.calls
        if name == "get_item"
    )


def test_dynamodb_predecessor_chain_and_conflicts() -> None:
    client = Dynamo()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    store.register("namespace-one", "run-first", "a" * 64)
    first = store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)
    head = store.publish(first, None, "b" * 64)
    store.register("namespace-one", "run-second", "c" * 64)
    second = store.admit("namespace-one", "run-second", "c" * 64, "attempt-two", OWNER)
    later = store.publish(second, head, "d" * 64)
    assert store.register("namespace-one", "run-first", "a" * 64) == head
    assert store.read_root("namespace-one")["predecessor"] == head
    assert later != head
    with pytest.raises(ControlRejected, match="immutable"):
        store.register("namespace-two", "run-first", "a" * 64)
    with pytest.raises(ControlRejected, match="immutable"):
        store.register("namespace-one", "run-first", "f" * 64)


def test_dynamodb_invalid_table_and_malformed_responses() -> None:
    with pytest.raises(ControlRejected, match="table"):
        DynamoDBAuthority(Dynamo(), "other")

    class Bad(Dynamo):
        def get_item(self, **request: Any) -> dict[str, Any]:
            return {"Item": []}

    with pytest.raises(ControlRejected, match="item"):
        DynamoDBAuthority(Bad(), "ledgerguard-test-control").read_root("namespace-one")

    class BadCounter(Dynamo):
        def update_item(self, **request: Any) -> dict[str, Any]:
            return {}

    client = BadCounter()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    store.register("namespace-one", "run-first", "a" * 64)
    with pytest.raises(ControlRejected, match="allocation"):
        store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)


def test_dynamodb_closed_attribute_decoding_and_get_response() -> None:
    for value in (None, {"N": "1"}, {"S": 1}, {"S": "x", "N": "1"}):
        with pytest.raises(ControlRejected, match="string"):
            DynamoDBAuthority._s({"value": value}, "value")
    for value in (None, {"S": "1"}, {"N": 1}, {"N": "0"}, {"N": str(2**63)}):
        with pytest.raises(ControlRejected, match=r"integer|exceeds"):
            DynamoDBAuthority._n({"value": value}, "value")

    class BadGet(Dynamo):
        def get_item(self, **request: Any) -> Any:
            return []

    with pytest.raises(ControlRejected, match="get response"):
        DynamoDBAuthority(BadGet(), "ledgerguard-test-control").read_root("namespace-one")


def test_dynamodb_missing_or_changed_registration_and_status_are_rejected() -> None:
    client = Dynamo()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    with pytest.raises(ControlRejected, match="registration is missing"):
        store._registration("namespace-one", "run-first", "a" * 64)
    store.register("namespace-one", "run-first", "a" * 64)
    item = client.items[("RUN#run-first", "REGISTRATION")]
    item["status"] = {"S": "FAILED"}
    with pytest.raises(ControlRejected, match="status differs"):
        store.register("namespace-one", "run-first", "a" * 64)


def test_dynamodb_admission_transaction_conflict_is_not_replayed() -> None:
    class Conflict(Dynamo):
        def transact_write_items(self, **request: Any) -> dict[str, Any]:
            raise ServiceError("TransactionCanceledException")

    client = Conflict()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    store.register("namespace-one", "run-first", "a" * 64)
    with pytest.raises(ControlRejected, match="admission failed"):
        store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)


def test_dynamodb_replay_requires_active_run_binding() -> None:
    client = Dynamo()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    store.register("namespace-one", "run-first", "a" * 64)
    store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)
    client.items[("RUN#run-first", "REGISTRATION")]["owner"] = {"S": OWNER + "-changed"}
    with pytest.raises(ControlRejected, match="active fenced"):
        store._replay_attempt("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)
    client.items[("RUN#run-first", "REGISTRATION")]["owner"] = {"S": OWNER}
    client.items[("RUN#run-first", "REGISTRATION")]["fence"] = {"N": "2"}
    with pytest.raises(ControlRejected, match="active fenced"):
        store._replay_attempt("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)


def test_dynamodb_commit_integrity_identity_and_reachability_fail_closed() -> None:
    client = Dynamo()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    store.register("namespace-one", "run-first", "a" * 64)
    attempt = store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)
    digest = store.publish(attempt, None, "b" * 64)
    commit_key = ("NAMESPACE#namespace-one", f"COMMIT#{digest}")
    original = deepcopy(client.items[commit_key])
    del client.items[commit_key]
    with pytest.raises(ControlRejected, match="commit is missing"):
        store._commit("namespace-one", digest)
    client.items[commit_key] = deepcopy(original)
    client.items[commit_key]["document"] = {"S": "{}"}
    with pytest.raises(ControlRejected, match="integrity"):
        store._commit("namespace-one", digest)
    client.items[commit_key] = deepcopy(original)
    with pytest.raises(ControlRejected, match="another identity"):
        store._require_reachable("namespace-one", digest, "other-run", "a" * 64)
    with pytest.raises(ControlRejected, match="another identity"):
        store._require_reachable("namespace-one", digest, "run-first", "f" * 64)
    with pytest.raises(ControlRejected, match="not reachable"):
        store._require_reachable("namespace-one", "c" * 64)


def test_dynamodb_cycle_guard_rejects_malformed_ancestry() -> None:
    class Cycle(DynamoDBAuthority):
        def _commit(self, namespace: str, digest: str) -> dict[str, Any]:
            return {"predecessor": digest}

    client = Dynamo()
    client.items[("NAMESPACE#namespace-one", "ROOT")] = {
        "pk": {"S": "NAMESPACE#namespace-one"},
        "sk": {"S": "ROOT"},
        "head": {"S": "a" * 64},
    }
    with pytest.raises(ControlRejected, match="cycle"):
        Cycle(client, "ledgerguard-test-control")._require_reachable(
            "namespace-one", "b" * 64
        )


def test_dynamodb_nonconditional_service_errors_are_not_recast() -> None:
    class Broken(Dynamo):
        def put_item(self, **request: Any) -> dict[str, Any]:
            raise ServiceError("AccessDeniedException")

    store = DynamoDBAuthority(Broken(), "ledgerguard-test-control")
    with pytest.raises(ServiceError):
        store.register("namespace-one", "run-first", "a" * 64)
    assert not DynamoDBAuthority._conditional(Exception("plain"))


def test_dynamodb_publication_conflict_does_not_become_success() -> None:
    client = Dynamo()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    store.register("namespace-one", "run-first", "a" * 64)
    attempt = store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)
    with pytest.raises(ControlRejected, match="not authoritative"):
        store.publish(attempt, "c" * 64, "b" * 64)


def test_dynamodb_failed_admission_cannot_replay_another_owner() -> None:
    client = Dynamo()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    store.register("namespace-one", "run-first", "a" * 64)
    store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)
    with pytest.raises(ControlRejected, match="reuse"):
        store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER + "-other")


def test_dynamodb_root_absent_is_not_authority() -> None:
    store = DynamoDBAuthority(Dynamo(), "ledgerguard-test-control")
    assert store.read_root("namespace-one") is None
    with pytest.raises(ControlRejected, match="missing"):
        store._require_reachable("namespace-one", "a" * 64)


def test_dynamodb_ancestry_depth_and_ambiguous_terminal_mismatch_are_rejected() -> None:
    class Endless(DynamoDBAuthority):
        count = 0

        def _commit(self, namespace: str, digest: str) -> dict[str, Any]:
            self.count += 1
            return {"predecessor": f"{self.count + 1:064x}"}

    client = Dynamo()
    client.items[("NAMESPACE#namespace-one", "ROOT")] = {
        "pk": {"S": "NAMESPACE#namespace-one"},
        "sk": {"S": "ROOT"},
        "head": {"S": f"{1:064x}"},
    }
    with pytest.raises(ControlRejected, match="not reachable"):
        Endless(client, "ledgerguard-test-control")._require_reachable(
            "namespace-one", "f" * 64
        )

    client = Dynamo()
    store = DynamoDBAuthority(client, "ledgerguard-test-control")
    store.register("namespace-one", "run-first", "a" * 64)
    attempt = store.admit("namespace-one", "run-first", "a" * 64, "attempt-one", OWNER)
    store.publish(attempt, None, "b" * 64)
    client.items[("RUN#run-first", "REGISTRATION")]["status"] = {"S": "REGISTERED"}
    with pytest.raises(ControlRejected, match="not authoritative"):
        store.publish(attempt, None, "b" * 64)
