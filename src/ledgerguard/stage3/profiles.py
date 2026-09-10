"""Frozen deterministic Stage 3 profile semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType

from .canonical import canonical_digest, semantic_id
from .errors import Stage3Rejected


@dataclass(frozen=True)
class Profile:
    name: str
    seed: int
    processor_event_count: int
    events_per_settlement: int
    shard_rows: int
    merchant_count: int
    currencies: tuple[str, ...]
    negative_event_cycle: tuple[str, ...] = ("REFUND", "CHARGEBACK", "REVERSAL")
    split_every_settlements: int = 10
    skew_cycle: int = 4
    skew_hotspot_slots: int = 3
    base_timestamp: str = "2026-09-01T00:00:00Z"
    generator_version: str = "1.0"

    def semantic_value(self) -> dict[str, object]:
        value = asdict(self)
        value["currencies"] = list(self.currencies)
        value["negative_event_cycle"] = list(self.negative_event_cycle)
        return value

    @property
    def profile_sha256(self) -> str:
        return canonical_digest(self.semantic_value())

    @property
    def dataset_id(self) -> str:
        return semantic_id("dataset", self.semantic_value())


PROFILES = MappingProxyType(
    {
        "correctness-small": Profile(
            "correctness-small",
            730031,
            16,
            4,
            8,
            2,
            ("INR", "USD", "JPY"),
        ),
        "local-10k": Profile("local-10k", 730031, 10_000, 100, 10_000, 8, ("INR", "USD", "JPY")),
        "local-100k": Profile(
            "local-100k", 730031, 100_000, 100, 50_000, 32, ("INR", "USD", "JPY")
        ),
        "managed-1m": Profile(
            "managed-1m", 730031, 1_000_000, 100, 100_000, 128, ("INR", "USD", "JPY")
        ),
    }
)


def validate_profile(profile: Profile) -> None:
    if profile.processor_event_count <= 0 or profile.events_per_settlement <= 0:
        raise Stage3Rejected("PROFILE_VIOLATION", "counts must be positive")
    if profile.shard_rows <= 0 or profile.merchant_count <= 0:
        raise Stage3Rejected("PROFILE_VIOLATION", "shard and merchant counts must be positive")
    if not profile.currencies or len(set(profile.currencies)) != len(profile.currencies):
        raise Stage3Rejected("PROFILE_VIOLATION", "currencies must be unique and nonempty")
    if profile.negative_event_cycle != ("REFUND", "CHARGEBACK", "REVERSAL"):
        raise Stage3Rejected("PROFILE_VIOLATION", "negative event cycle is not frozen")
    if profile.split_every_settlements <= 0:
        raise Stage3Rejected("PROFILE_VIOLATION", "split frequency must be positive")
    if not 0 < profile.skew_hotspot_slots < profile.skew_cycle:
        raise Stage3Rejected("PROFILE_VIOLATION", "skew concentration is invalid")
    if profile.name not in PROFILES or PROFILES[profile.name] != profile:
        raise Stage3Rejected("PROFILE_VIOLATION", "profile is not a frozen registry member")


def profile_identity(name: str) -> str:
    try:
        profile = PROFILES[name]
    except KeyError as error:
        raise Stage3Rejected("PROFILE_VIOLATION", f"unknown profile: {name}") from error
    validate_profile(profile)
    return profile.dataset_id


def get_profile(name: str) -> Profile:
    """Return a validated frozen profile by name."""
    try:
        value = PROFILES[name]
    except KeyError as error:
        raise Stage3Rejected("PROFILE_VIOLATION", f"unknown profile: {name}") from error
    validate_profile(value)
    return value
