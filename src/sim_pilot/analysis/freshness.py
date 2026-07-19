"""Fail-closed, identity-bound snapshot freshness policy."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from sim_pilot.domain.world import WorldSnapshot
from sim_pilot.private_files import atomic_write_private_text


class SnapshotIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    world_id: str
    save_generation: int
    capability_fingerprint: str

    @classmethod
    def from_snapshot(cls, snapshot: WorldSnapshot) -> SnapshotIdentity:
        metadata = snapshot.metadata
        return cls(
            world_id=metadata.world_id,
            save_generation=metadata.save_generation,
            capability_fingerprint=metadata.capability_fingerprint,
        )


class SnapshotCacheRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    stored_at: AwareDatetime
    identity: SnapshotIdentity
    snapshot: WorldSnapshot


class SnapshotCache:
    """Reuse only complete snapshots whose live identity has been independently verified."""

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
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    def store(self, snapshot: WorldSnapshot) -> None:
        if not snapshot.metadata.complete:
            return
        record = SnapshotCacheRecord(
            stored_at=self._clock(),
            identity=SnapshotIdentity.from_snapshot(snapshot),
            snapshot=snapshot,
        )
        atomic_write_private_text(self._path, record.model_dump_json(indent=2))

    def load(
        self, verified_identity: SnapshotIdentity | None
    ) -> tuple[WorldSnapshot, float] | None:
        # A cache timestamp alone cannot prove that the game has not loaded another save.
        if verified_identity is None or not self._path.is_file():
            return None
        record = SnapshotCacheRecord.model_validate_json(
            self._path.read_text(encoding="utf-8"), strict=True
        )
        age = max(0.0, (self._clock() - record.stored_at).total_seconds())
        if age > self._ttl_seconds or not record.snapshot.metadata.complete:
            return None
        if record.identity != verified_identity:
            return None
        return record.snapshot, age
