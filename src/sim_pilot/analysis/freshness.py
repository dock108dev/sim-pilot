"""Fail-closed, identity-bound snapshot freshness policy."""

from __future__ import annotations

import fcntl
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from sim_pilot.domain.world import WorldSnapshot
from sim_pilot.private_files import atomic_write_private_text, ensure_private_directory


class SnapshotIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    world_id: str = Field(min_length=1)
    save_generation: int = Field(ge=0)
    capability_fingerprint: str = Field(min_length=1)
    observer_company_id: str = Field(min_length=1)
    bridge_company_context: int = Field(ge=0, le=14)

    @classmethod
    def from_snapshot(
        cls, snapshot: WorldSnapshot, *, bridge_company_context: int
    ) -> SnapshotIdentity:
        metadata = snapshot.metadata
        if metadata.observer_company_id is None:
            raise ValueError("snapshot observer company identity is unavailable")
        return cls(
            world_id=metadata.world_id,
            save_generation=metadata.save_generation,
            capability_fingerprint=metadata.capability_fingerprint,
            observer_company_id=metadata.observer_company_id,
            bridge_company_context=bridge_company_context,
        )


class SnapshotVerification(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    identity: SnapshotIdentity
    verified_at: AwareDatetime
    bridge_sequence: int = Field(ge=1)
    synchronization_state: Literal["identity_verified", "synchronized"]
    openttd_version: str = Field(min_length=1)
    bridge_protocol_version: int = Field(ge=1)
    script_version: int = Field(ge=1)


class SnapshotCacheRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[2] = 2
    stored_at: AwareDatetime
    identity: SnapshotIdentity
    collection_duration_seconds: float = Field(ge=0)
    snapshot: WorldSnapshot

    @model_validator(mode="after")
    def validate_identity_matches_snapshot(self) -> Self:
        metadata = self.snapshot.metadata
        if (
            self.identity.world_id != metadata.world_id
            or self.identity.save_generation != metadata.save_generation
            or self.identity.capability_fingerprint != metadata.capability_fingerprint
            or self.identity.observer_company_id != metadata.observer_company_id
        ):
            raise ValueError("cached identity does not match cached snapshot metadata")
        return self


class SnapshotCacheStatus(StrEnum):
    HIT = "hit"
    REQUIRES_VERIFICATION = "requires_verification"
    MISSING = "missing"
    CORRUPT = "corrupt"
    EXPIRED = "expired"
    INCOMPATIBLE = "incompatible"
    INCOMPLETE = "incomplete"


class SnapshotCacheLookup(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    status: SnapshotCacheStatus
    snapshot: WorldSnapshot | None = None
    age_seconds: float | None = Field(default=None, ge=0)
    collection_duration_seconds: float | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_hit(self) -> Self:
        if self.status is SnapshotCacheStatus.HIT:
            if (
                self.snapshot is None
                or self.age_seconds is None
                or self.collection_duration_seconds is None
            ):
                raise ValueError("cache hit requires snapshot age and collection duration")
        elif self.snapshot is not None:
            raise ValueError("cache misses cannot expose an unverified snapshot")
        return self


class SnapshotCache:
    """Reuse only complete snapshots whose live identity was independently verified."""

    def __init__(
        self,
        path: Path,
        *,
        ttl_seconds: float = 30,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if ttl_seconds < 0:
            raise ValueError("snapshot cache TTL must not be negative")
        self._path = path
        self._lock_path = path.with_suffix(f"{path.suffix}.lock")
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    @contextmanager
    def exclusive(self) -> Generator[None]:
        """Serialize cache check/probe/refresh across concurrent CLI processes."""
        ensure_private_directory(self._lock_path.parent)
        descriptor = os.open(self._lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def store(
        self,
        snapshot: WorldSnapshot,
        *,
        identity: SnapshotIdentity,
        collection_duration_seconds: float,
    ) -> None:
        if not snapshot.metadata.complete:
            return
        record = SnapshotCacheRecord(
            stored_at=self._clock(),
            identity=identity,
            collection_duration_seconds=collection_duration_seconds,
            snapshot=snapshot,
        )
        atomic_write_private_text(self._path, record.model_dump_json(indent=2))

    def candidate_status(self, maximum_age_seconds: float) -> SnapshotCacheLookup:
        """Report whether a candidate merits a live identity probe without exposing it."""
        record, failure = self._read()
        if failure is not None:
            return failure
        assert record is not None
        age = self._age(record)
        if not record.snapshot.metadata.complete:
            return SnapshotCacheLookup(
                status=SnapshotCacheStatus.INCOMPLETE,
                age_seconds=age,
                reason="cached snapshot is incomplete",
            )
        if age > self._effective_age(maximum_age_seconds):
            return SnapshotCacheLookup(
                status=SnapshotCacheStatus.EXPIRED,
                age_seconds=age,
                reason="cached snapshot exceeds the freshness policy",
            )
        return SnapshotCacheLookup(
            status=SnapshotCacheStatus.REQUIRES_VERIFICATION,
            age_seconds=age,
            reason="fresh candidate requires independent identity verification",
        )

    def load(
        self,
        verified_identity: SnapshotIdentity | None,
        *,
        maximum_age_seconds: float,
    ) -> SnapshotCacheLookup:
        if verified_identity is None:
            return SnapshotCacheLookup(
                status=SnapshotCacheStatus.INCOMPATIBLE,
                reason="live snapshot identity was not independently verified",
            )
        record, failure = self._read()
        if failure is not None:
            return failure
        assert record is not None
        age = self._age(record)
        if not record.snapshot.metadata.complete:
            return SnapshotCacheLookup(
                status=SnapshotCacheStatus.INCOMPLETE,
                age_seconds=age,
                reason="cached snapshot is incomplete",
            )
        if age > self._effective_age(maximum_age_seconds):
            return SnapshotCacheLookup(
                status=SnapshotCacheStatus.EXPIRED,
                age_seconds=age,
                reason="cached snapshot exceeds the freshness policy",
            )
        if record.identity != verified_identity:
            return SnapshotCacheLookup(
                status=SnapshotCacheStatus.INCOMPATIBLE,
                age_seconds=age,
                reason="cached world, company, bridge generation, or capabilities changed",
            )
        return SnapshotCacheLookup(
            status=SnapshotCacheStatus.HIT,
            snapshot=record.snapshot,
            age_seconds=age,
            collection_duration_seconds=record.collection_duration_seconds,
            reason="cached snapshot passed freshness and live identity verification",
        )

    def _read(self) -> tuple[SnapshotCacheRecord | None, SnapshotCacheLookup | None]:
        if not self._path.is_file():
            return None, SnapshotCacheLookup(
                status=SnapshotCacheStatus.MISSING,
                reason="snapshot cache does not exist",
            )
        try:
            record = SnapshotCacheRecord.model_validate_json(
                self._path.read_text(encoding="utf-8"), strict=True
            )
        except (OSError, ValidationError, ValueError):
            return None, SnapshotCacheLookup(
                status=SnapshotCacheStatus.CORRUPT,
                reason="snapshot cache failed strict validation",
            )
        return record, None

    def _age(self, record: SnapshotCacheRecord) -> float:
        return max(0.0, (self._clock() - record.snapshot.metadata.captured_at).total_seconds())

    def _effective_age(self, maximum_age_seconds: float) -> float:
        if maximum_age_seconds < 0:
            raise ValueError("maximum snapshot age must not be negative")
        return min(maximum_age_seconds, self._ttl_seconds)
