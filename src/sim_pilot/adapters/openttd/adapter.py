"""Runtime adapter for observed and narrowly verified OpenTTD actions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.adapters.base import (
    ActionDefinition,
    ActionParameterDefinition,
    ActionParameterType,
)
from sim_pilot.domain import Action, ExecutionResult, Observation
from sim_pilot.openttd.gamescript.client import GameScriptBridgeClient
from sim_pilot.openttd.gamescript.errors import BridgeCommandError
from sim_pilot.openttd.gamescript.models import BridgeHealth, SynchronizationState
from sim_pilot.openttd.models import (
    OpenTTDAdapterCapabilities,
    OpenTTDClient,
    OpenTTDObservationState,
    OpenTTDState,
)

SET_SERVER_NAME = "set_server_name"
SET_COMPANY_NAME = "set_company_name"
MAX_SERVER_NAME_BYTES = 79


class SetServerNameOpenTTDAction(BaseModel):
    """The only Task 6C action with an independently observable postcondition."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    action_type: Literal["set_server_name"] = SET_SERVER_NAME
    name: str = Field(min_length=1)

    @classmethod
    def from_action(cls, action: Action) -> SetServerNameOpenTTDAction:
        if action.type != SET_SERVER_NAME:
            raise ValueError(f"unsupported OpenTTD action: {action.type}")
        if set(action.parameters) != {"name"}:
            raise ValueError("set_server_name requires exactly the 'name' parameter")
        value = action.parameters.get("name")
        if not isinstance(value, str):
            raise ValueError("set_server_name name must be a string")
        candidate = cls(name=value)
        if candidate.name != candidate.name.strip():
            raise ValueError("server name must not have leading or trailing whitespace")
        if len(candidate.name.encode("utf-8")) > MAX_SERVER_NAME_BYTES:
            raise ValueError("server name exceeds OpenTTD's 79-byte UTF-8 limit")
        if any(character in candidate.name for character in ('"', "\\", ";")) or any(
            ord(character) < 32 for character in candidate.name
        ):
            raise ValueError("server name contains an unsafe console character")
        return candidate

    def command(self) -> str:
        return f'server_name "{self.name}"'


class SetCompanyNameOpenTTDAction(BaseModel):
    """The only Task 7A-verified GameScript company mutation."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    action_type: Literal["set_company_name"] = SET_COMPANY_NAME
    name: str = Field(min_length=1, max_length=128)

    @classmethod
    def from_action(cls, action: Action) -> SetCompanyNameOpenTTDAction:
        if action.type != SET_COMPANY_NAME:
            raise ValueError(f"unsupported OpenTTD GameScript action: {action.type}")
        if set(action.parameters) != {"name"}:
            raise ValueError("set_company_name requires exactly the 'name' parameter")
        name = action.parameters.get("name")
        if not isinstance(name, str):
            raise ValueError("set_company_name name must be a string")
        candidate = cls(name=name)
        if candidate.name != candidate.name.strip():
            raise ValueError("company name must not have leading or trailing whitespace")
        if any(ord(character) < 32 for character in candidate.name):
            raise ValueError("company name contains a control character")
        return candidate


class OpenTTDValidation(BaseModel):
    """Typed deterministic adapter validation result."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    valid: bool
    message: str = Field(min_length=1)
    estimated_cost: float = 0.0
    code: str = Field(min_length=1)
    state_stale: bool = False


class OpenTTDAdapter:
    """Translate Admin Network state and one safe RCON setting into runtime contracts."""

    requires_fresh_observation_on_resume = True

    def __init__(
        self,
        client: OpenTTDClient,
        *,
        allow_writes: bool = False,
        stale_days: int = 3,
        action_timeout_seconds: float = 5.0,
        bridge: GameScriptBridgeClient | None = None,
        allow_gamescript_writes: bool = False,
    ) -> None:
        self.client = client
        self.allow_writes = allow_writes
        self.stale_days = stale_days
        self.action_timeout_seconds = action_timeout_seconds
        self.bridge = bridge
        self.allow_gamescript_writes = allow_gamescript_writes
        self._initialized = False
        self._observation_sequence = 0
        self._pending_state: OpenTTDState | None = None
        self._last_observed_state: OpenTTDState | None = None
        self._pending_bridge_health: BridgeHealth | None = None
        self._last_bridge_health: BridgeHealth | None = None

    @property
    def capabilities(self) -> OpenTTDAdapterCapabilities:
        rcon_writable = self._initialized and self.allow_writes
        bridge_health = self.bridge.health if self.bridge is not None else None
        bridge_capabilities = None if bridge_health is None else bridge_health.capabilities
        bridge_detected = (
            bridge_health is not None
            and bridge_health.synchronization_state is SynchronizationState.SYNCHRONIZED
        )
        bridge_actions = (
            () if bridge_capabilities is None else bridge_capabilities.supported_actions
        )
        company_name_writable = (
            bridge_detected and self.allow_gamescript_writes and SET_COMPANY_NAME in bridge_actions
        )
        return OpenTTDAdapterCapabilities(
            execute_actions=rcon_writable or company_name_writable,
            supports_reconciliation=rcon_writable or company_name_writable,
            supports_set_server_name=rcon_writable,
            bridge_detected=bridge_detected,
            supports_full_snapshots=(
                bridge_detected
                and bridge_capabilities is not None
                and bridge_capabilities.full_snapshots
            ),
            supports_set_company_name=company_name_writable,
            bridge_read_resources=(
                () if bridge_capabilities is None else bridge_capabilities.readable_resources
            ),
            bridge_actions=bridge_actions,
        )

    async def initialize(self) -> None:
        await self.client.connect()
        try:
            self._pending_state = await self.client.collect_state()
            if self.bridge is not None:
                self._pending_bridge_health = await self.bridge.synchronize()
        except Exception:
            await self.client.close()
            raise
        self._initialized = True

    async def observe(self) -> Observation:
        self._require_initialized()
        game_state = self._pending_state or await self.client.collect_state()
        self._pending_state = None
        self._last_observed_state = game_state
        bridge_health = self._pending_bridge_health
        self._pending_bridge_health = None
        if self.bridge is not None and bridge_health is None:
            await self.bridge.refresh_snapshot()
            bridge_health = self.bridge.health
        self._last_bridge_health = bridge_health
        if bridge_health is None:
            basic = OpenTTDObservationState.from_game_state(game_state)
            state = basic.model_copy(
                update={
                    "adapter": basic.adapter.model_copy(update={"capabilities": self.capabilities})
                }
            )
        else:
            state = OpenTTDObservationState.from_combined_state(
                game_state, bridge_health, self.capabilities
            )
        self._observation_sequence += 1
        company = game_state.company
        summary = (
            f"OpenTTD {game_state.game_date}: company={company.company_id} "
            f"cash={company.cash} loan={company.loan} "
            f"profit={company.net_income_current_year} vehicles={company.vehicles.total} "
            f"facilities={company.station_facilities.total}"
        )
        if bridge_health is not None and bridge_health.snapshot is not None:
            summary += (
                f" towns={bridge_health.snapshot.town_count}"
                f" industries={bridge_health.snapshot.industry_count}"
                f" paused={bridge_health.snapshot.paused}"
                f" bridge={bridge_health.synchronization_state.value}"
            )
        return Observation(
            sequence=self._observation_sequence,
            timestamp=datetime.now(UTC),
            tick=game_state.game_date_raw,
            summary=summary,
            state=cast("dict[str, object]", state.model_dump(mode="json")),
        )

    async def available_actions(self) -> list[ActionDefinition]:
        self._require_initialized()
        actions: list[ActionDefinition] = []
        if self.capabilities.supports_set_server_name:
            actions.append(
                ActionDefinition(
                    type=SET_SERVER_NAME,
                    parameters=(
                        ActionParameterDefinition(
                            name="name",
                            type=ActionParameterType.STRING,
                        ),
                    ),
                    description=(
                        "Set the dedicated server name through Admin Network RCON; "
                        "verified after reconnecting to SERVER_WELCOME."
                    ),
                )
            )
        if self.capabilities.supports_set_company_name:
            actions.append(
                ActionDefinition(
                    type=SET_COMPANY_NAME,
                    parameters=(
                        ActionParameterDefinition(
                            name="name",
                            type=ActionParameterType.STRING,
                        ),
                    ),
                    description=(
                        "Set the selected existing company's name through GameScript; "
                        "test-mode checked and verified by a fresh bridge snapshot."
                    ),
                )
            )
        return actions

    async def validate(self, action: Action) -> OpenTTDValidation:
        self._require_initialized()
        if action.type == SET_COMPANY_NAME:
            return await self._validate_company_name(action)
        if not self.allow_writes:
            return self._invalid("writes_disabled", "OpenTTD writes require explicit opt-in")
        try:
            typed = SetServerNameOpenTTDAction.from_action(action)
        except ValueError as error:
            return self._invalid("invalid_action", str(error))
        before = self._last_observed_state
        if before is None:
            return self._invalid(
                "missing_observation", "an observation is required before execution"
            )
        fresh = await self.client.collect_state()
        self._pending_state = fresh
        drift = self._drift_reason(before, fresh)
        if drift is not None:
            return self._invalid("stale_observation", drift, state_stale=True)
        if fresh.connection.server_name == typed.name:
            return self._invalid("already_satisfied", "server name already has the requested value")
        return OpenTTDValidation(
            valid=True,
            message="OpenTTD server-name change is valid",
            code="valid",
        )

    async def execute(self, action: Action) -> ExecutionResult:
        self._require_initialized()
        if action.type == SET_COMPANY_NAME:
            return await self._execute_company_name(action)
        if not self.allow_writes:
            return ExecutionResult(
                success=False,
                state_changed=False,
                cost=0.0,
                message="OpenTTD write was not sent because write opt-in is disabled.",
            )
        typed = SetServerNameOpenTTDAction.from_action(action)
        prior = self._last_observed_state
        output = await self.client.execute_rcon(typed.command())
        await self.client.reconnect()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.action_timeout_seconds
        observed: OpenTTDState | None = None
        while loop.time() < deadline:
            observed = await self.client.collect_state()
            if observed.connection.server_name == typed.name:
                self._pending_state = observed
                changed = prior is None or prior.connection.server_name != typed.name
                detail = "; ".join(output) if output else "RCON completed"
                return ExecutionResult(
                    success=True,
                    state_changed=changed,
                    cost=0.0,
                    message=f"{detail}; observed server name {typed.name!r} after reconnect.",
                )
            await asyncio.sleep(0.1)
        if observed is not None:
            self._pending_state = observed
        return ExecutionResult(
            success=False,
            state_changed=False,
            cost=0.0,
            message="RCON completed but the requested server name was not observed.",
        )

    async def shutdown(self) -> None:
        if self.bridge is None:
            await self.client.close()
        else:
            await self.bridge.close()
        self._initialized = False
        self._pending_state = None
        self._pending_bridge_health = None

    async def _validate_company_name(self, action: Action) -> OpenTTDValidation:
        if not self.allow_gamescript_writes:
            return self._invalid("writes_disabled", "GameScript writes require explicit opt-in")
        if self.bridge is None or not self.capabilities.supports_set_company_name:
            return self._invalid(
                "unsupported_action", "running bridge does not support set_company_name"
            )
        try:
            typed = SetCompanyNameOpenTTDAction.from_action(action)
        except ValueError as error:
            return self._invalid("invalid_action", str(error))
        before = self._last_bridge_health
        if before is None or before.snapshot is None:
            return self._invalid(
                "missing_observation", "a bridge observation is required before execution"
            )
        await self.bridge.refresh_snapshot()
        fresh = self.bridge.health
        self._pending_bridge_health = fresh
        if fresh.snapshot is None or fresh.snapshot.company is None:
            return self._invalid("invalid_company", "selected company is unavailable")
        if before.script_instance_id != fresh.script_instance_id:
            return self._invalid(
                "stale_observation",
                "GameScript identity changed after observation",
                state_stale=True,
            )
        if before.snapshot.company is None or (
            before.snapshot.company.name != fresh.snapshot.company.name
        ):
            return self._invalid(
                "stale_observation", "company name changed after observation", state_stale=True
            )
        if fresh.snapshot.company.name == typed.name:
            return self._invalid("already_satisfied", "company name already has requested value")
        return OpenTTDValidation(
            valid=True,
            message="OpenTTD company-name change is valid",
            code="valid",
        )

    async def _execute_company_name(self, action: Action) -> ExecutionResult:
        if not self.allow_gamescript_writes or self.bridge is None:
            return ExecutionResult(
                success=False,
                state_changed=False,
                cost=0.0,
                message="GameScript write was not sent because write opt-in is disabled.",
            )
        typed = SetCompanyNameOpenTTDAction.from_action(action)
        health = self._pending_bridge_health or self.bridge.health
        if health.snapshot is None:
            return ExecutionResult(
                success=False,
                state_changed=False,
                cost=0.0,
                message="GameScript write was not sent because no synchronized snapshot exists.",
            )
        try:
            completed, _ = await self.bridge.execute_set_company_name(
                name=typed.name,
                prior_snapshot_id=health.snapshot.snapshot_id,
            )
        except BridgeCommandError as error:
            return ExecutionResult(
                success=False,
                state_changed=False,
                cost=0.0,
                message=str(error),
            )
        self._pending_bridge_health = self.bridge.health
        return ExecutionResult(
            success=True,
            state_changed=completed.state_changed,
            cost=float(completed.cost),
            message=(
                f"GameScript command {completed.command_id} completed and a fresh snapshot "
                f"verified company name {completed.after_name!r}."
            ),
        )

    def _drift_reason(self, before: OpenTTDState, current: OpenTTDState) -> str | None:
        if before.connection != current.connection or before.map != current.map:
            return "OpenTTD server or map identity changed after the decision observation"
        if before.company.company_id != current.company.company_id:
            return "OpenTTD company identity changed after the decision observation"
        delta = current.game_date_raw - before.game_date_raw
        if delta < 0 or delta > self.stale_days:
            return f"OpenTTD game date moved by {delta} days after the decision observation"
        return None

    @staticmethod
    def _invalid(code: str, message: str, *, state_stale: bool = False) -> OpenTTDValidation:
        return OpenTTDValidation(
            valid=False,
            message=message,
            code=code,
            state_stale=state_stale,
        )

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("OpenTTD adapter is not initialized.")


# Preserve the Task 6B import while evolving its capabilities in Task 6C.
OpenTTDReadOnlyAdapter = OpenTTDAdapter
