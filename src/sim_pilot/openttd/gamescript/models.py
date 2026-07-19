"""Runtime-neutral bridge health and synchronization models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sim_pilot.openttd.gamescript.messages import (
    BridgeCapabilities,
    BridgeCargoEntity,
    BridgeCompanyEntity,
    BridgeIndustryEntity,
    BridgeOrderEntity,
    BridgeSnapshot,
    BridgeStationEntity,
    BridgeTownEntity,
    BridgeVehicleEntity,
)


class BridgeWorldSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    snapshot_id: str
    capture_started_game_date: int = Field(ge=0)
    capture_completed_game_date: int = Field(ge=0)
    complete: bool = True
    companies: tuple[BridgeCompanyEntity, ...] = ()
    towns: tuple[BridgeTownEntity, ...] = ()
    industries: tuple[BridgeIndustryEntity, ...] = ()
    stations: tuple[BridgeStationEntity, ...] = ()
    vehicles: tuple[BridgeVehicleEntity, ...] = ()
    orders: tuple[BridgeOrderEntity, ...] = ()
    cargos: tuple[BridgeCargoEntity, ...] = ()


class SynchronizationState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    AWAITING_HELLO = "awaiting_hello"
    AWAITING_CAPABILITIES = "awaiting_capabilities"
    AWAITING_SNAPSHOT = "awaiting_snapshot"
    SYNCHRONIZED = "synchronized"
    DEGRADED = "degraded"
    RESYNCHRONIZING = "resynchronizing"
    INCOMPATIBLE = "incompatible"
    FAILED = "failed"


class BridgeHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    connected: bool
    authenticated: bool
    openttd_version: str | None = None
    bridge_detected: bool
    bridge_protocol_version: int | None = Field(default=None, ge=1)
    script_version: int | None = Field(default=None, ge=1)
    script_instance_id: str | None = None
    last_sequence: int | None = Field(default=None, ge=1)
    last_heartbeat: AwareDatetime | None = None
    last_snapshot_at: AwareDatetime | None = None
    synchronization_state: SynchronizationState
    active_company_context: int | None = Field(default=None, ge=0, le=14)
    capability_fingerprint: str | None = None
    capabilities: BridgeCapabilities | None = None
    snapshot: BridgeSnapshot | None = None
    world_snapshot: BridgeWorldSnapshot | None = None
    degraded_reason: str | None = None

    @classmethod
    def disconnected(cls) -> BridgeHealth:
        return cls(
            connected=False,
            authenticated=False,
            bridge_detected=False,
            synchronization_state=SynchronizationState.DISCONNECTED,
        )


def utc_now() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
