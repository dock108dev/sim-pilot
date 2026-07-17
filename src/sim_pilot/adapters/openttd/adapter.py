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
from sim_pilot.openttd.models import (
    OpenTTDAdapterCapabilities,
    OpenTTDClient,
    OpenTTDObservationState,
    OpenTTDState,
)

SET_SERVER_NAME = "set_server_name"
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
    ) -> None:
        self.client = client
        self.allow_writes = allow_writes
        self.stale_days = stale_days
        self.action_timeout_seconds = action_timeout_seconds
        self._initialized = False
        self._observation_sequence = 0
        self._pending_state: OpenTTDState | None = None
        self._last_observed_state: OpenTTDState | None = None

    @property
    def capabilities(self) -> OpenTTDAdapterCapabilities:
        writable = self._initialized and self.allow_writes
        return OpenTTDAdapterCapabilities(
            execute_actions=writable,
            supports_reconciliation=writable,
            supports_set_server_name=writable,
        )

    async def initialize(self) -> None:
        await self.client.connect()
        try:
            self._pending_state = await self.client.collect_state()
        except Exception:
            await self.client.close()
            raise
        self._initialized = True

    async def observe(self) -> Observation:
        self._require_initialized()
        game_state = self._pending_state or await self.client.collect_state()
        self._pending_state = None
        self._last_observed_state = game_state
        state = OpenTTDObservationState.from_game_state(game_state).model_copy(
            update={
                "adapter": OpenTTDObservationState.from_game_state(game_state).adapter.model_copy(
                    update={"capabilities": self.capabilities}
                )
            }
        )
        self._observation_sequence += 1
        company = game_state.company
        summary = (
            f"OpenTTD {game_state.game_date}: company={company.company_id} "
            f"cash={company.cash} loan={company.loan} "
            f"profit={company.net_income_current_year} vehicles={company.vehicles.total} "
            f"facilities={company.station_facilities.total}"
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
        if not self.capabilities.supports_set_server_name:
            return []
        return [
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
        ]

    async def validate(self, action: Action) -> OpenTTDValidation:
        self._require_initialized()
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
        await self.client.close()
        self._initialized = False
        self._pending_state = None

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
