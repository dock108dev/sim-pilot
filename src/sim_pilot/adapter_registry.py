"""Single typed registry for known integration availability and authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.domain import AdapterId


class AdapterRegistration(BaseModel):
    """Truthful application-level status for one known integration."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    adapter_id: AdapterId
    display_name: str = Field(min_length=1)
    flagship: bool = False
    frozen_reference: bool = False
    discovery_available: bool
    compiler_available: bool
    runtime_factory_available: bool
    observation_available: bool
    reconciliation_available: bool
    direct_ui_actions: tuple[str, ...] = ()
    advertised_actions: tuple[str, ...] = ()
    unavailable_reason: str | None = None


_REGISTRATIONS = {
    AdapterId.REFERENCE: AdapterRegistration(
        adapter_id=AdapterId.REFERENCE,
        display_name="Deterministic reference simulation",
        discovery_available=True,
        compiler_available=True,
        runtime_factory_available=True,
        observation_available=True,
        reconciliation_available=True,
        advertised_actions=(
            "advance_time",
            "build_housing",
            "build_power",
            "repair",
            "set_maintenance",
            "take_loan",
            "repay_loan",
            "pause",
            "resume",
        ),
    ),
    AdapterId.OPENTTD: AdapterRegistration(
        adapter_id=AdapterId.OPENTTD,
        display_name="OpenTTD",
        discovery_available=True,
        compiler_available=True,
        runtime_factory_available=True,
        observation_available=True,
        reconciliation_available=True,
        advertised_actions=("set_server_name", "set_company_name"),
    ),
    AdapterId.RAIL_ROUTE: AdapterRegistration(
        adapter_id=AdapterId.RAIL_ROUTE,
        display_name="Rail Route reference integration",
        discovery_available=True,
        compiler_available=False,
        runtime_factory_available=False,
        observation_available=True,
        reconciliation_available=False,
        advertised_actions=("pause", "resume", "set_route_ui"),
        unavailable_reason="Rail Route control is not composed through the persisted task runtime",
    ),
    AdapterId.SOFTWARE_INC: AdapterRegistration(
        adapter_id=AdapterId.SOFTWARE_INC,
        display_name="Software Inc. frozen reference integration",
        frozen_reference=True,
        discovery_available=True,
        compiler_available=False,
        runtime_factory_available=False,
        observation_available=True,
        reconciliation_available=False,
        direct_ui_actions=("open_manage_teams", "pause", "resume"),
        advertised_actions=(),
        unavailable_reason=(
            "The game-specific roadmap is frozen and the generic persisted-task runtime is "
            "unavailable; separately verified direct visible-UI actions remain available as "
            "reference capability"
        ),
    ),
}


def adapter_registration(adapter_id: AdapterId | str) -> AdapterRegistration:
    """Return a known adapter registration or fail without fallback."""
    try:
        canonical = adapter_id if isinstance(adapter_id, AdapterId) else AdapterId(adapter_id)
        return _REGISTRATIONS[canonical]
    except (KeyError, ValueError) as error:
        raise ValueError(f"unsupported adapter type: {adapter_id!r}") from error


def adapter_registrations() -> tuple[AdapterRegistration, ...]:
    """Return every registration in stable identifier order."""
    return tuple(_REGISTRATIONS[key] for key in sorted(_REGISTRATIONS, key=str))
