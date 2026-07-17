"""Runtime adapter for read-only OpenTTD Admin Network observations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.adapters.base import ActionDefinition
from sim_pilot.domain import Action, ExecutionResult, Observation
from sim_pilot.openttd.models import (
    OpenTTDAdapterCapabilities,
    OpenTTDClient,
    OpenTTDObservationState,
    OpenTTDState,
)


class ReadOnlyValidation(BaseModel):
    """Deterministic rejection returned by the Task 6B adapter."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    valid: bool = False
    message: str = Field(min_length=1)
    estimated_cost: float = 0.0


class OpenTTDReadOnlyAdapter:
    """Translate official Admin Network snapshots to canonical observations."""

    capabilities = OpenTTDAdapterCapabilities()

    def __init__(self, client: OpenTTDClient) -> None:
        self.client = client
        self._initialized = False
        self._observation_sequence = 0
        self._pending_state: OpenTTDState | None = None

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
        game_state = self._pending_state
        if game_state is None:
            game_state = await self.client.collect_state()
        self._pending_state = None
        state = OpenTTDObservationState.from_game_state(game_state)
        self._observation_sequence += 1
        company = game_state.company
        summary = (
            f"OpenTTD {game_state.game_date}: company={company.company_id} "
            f"cash={company.cash} loan={company.loan} profit={company.net_income_current_year} "
            f"vehicles={company.vehicles.total} facilities={company.station_facilities.total}"
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
        return []

    async def validate(self, action: Action) -> ReadOnlyValidation:
        self._require_initialized()
        return ReadOnlyValidation(
            message=f"OpenTTD adapter is read-only; action '{action.type}' is unavailable."
        )

    async def execute(self, action: Action) -> ExecutionResult:
        self._require_initialized()
        return ExecutionResult(
            success=False,
            state_changed=False,
            cost=0.0,
            message=f"OpenTTD adapter is read-only; action '{action.type}' was not sent.",
        )

    async def shutdown(self) -> None:
        await self.client.close()
        self._initialized = False
        self._pending_state = None

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError("OpenTTD adapter is not initialized.")
