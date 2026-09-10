"""Fail-closed Stage 3 error taxonomy."""


class Stage3Rejected(ValueError):
    """A deterministic contract, data, package, or runtime boundary was rejected."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail
        self.authoritative_proof = False
