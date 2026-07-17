"""Adapter boundary between the runtime and reference simulation."""

from datetime import UTC, datetime
from typing import cast

from pydantic import TypeAdapter, ValidationError

from sim_pilot.adapters.base import (
    ActionDefinition,
    ActionParameterDefinition,
    ActionParameterType,
    AdapterSnapshot,
)
from sim_pilot.domain import Action, ExecutionResult, Observation
from sim_pilot.domain.models import JsonValue
from sim_pilot.reference_simulation import ReferenceSimulation, SimulationAction, ValidationResult
from sim_pilot.reference_simulation.validation import invalid

ACTION_DEFINITIONS = (
    ActionDefinition(
        type="advance_time",
        parameters=(
            ActionParameterDefinition(name="ticks", type=ActionParameterType.INTEGER, minimum=1),
        ),
        description="Advance the simulation by one or more ticks.",
    ),
    ActionDefinition(
        type="build_housing",
        parameters=(
            ActionParameterDefinition(name="units", type=ActionParameterType.INTEGER, minimum=1),
        ),
        description="Start a housing construction project.",
    ),
    ActionDefinition(
        type="build_power",
        parameters=(
            ActionParameterDefinition(name="capacity", type=ActionParameterType.INTEGER, minimum=1),
        ),
        description="Start a power construction project.",
    ),
    ActionDefinition(
        type="repair",
        parameters=(
            ActionParameterDefinition(
                name="amount",
                type=ActionParameterType.NUMBER,
                minimum=0,
                exclusive_minimum=True,
            ),
        ),
        description="Repair infrastructure immediately.",
    ),
    ActionDefinition(
        type="set_maintenance",
        parameters=(
            ActionParameterDefinition(
                name="level",
                type=ActionParameterType.NUMBER,
                allowed_values=(0.0, 0.5, 1.0),
            ),
        ),
        description="Set the recurring maintenance level.",
    ),
    ActionDefinition(
        type="take_loan",
        parameters=(
            ActionParameterDefinition(
                name="amount",
                type=ActionParameterType.NUMBER,
                minimum=10_000,
                maximum=500_000,
            ),
        ),
        description="Take a loan within the debt limits.",
    ),
    ActionDefinition(
        type="repay_loan",
        parameters=(
            ActionParameterDefinition(
                name="amount",
                type=ActionParameterType.NUMBER,
                minimum=0,
                exclusive_minimum=True,
            ),
        ),
        description="Repay outstanding debt from cash.",
    ),
    ActionDefinition(type="pause", description="Pause simulation progression."),
    ActionDefinition(type="resume", description="Resume simulation progression."),
)

ACTION_ADAPTER: TypeAdapter[SimulationAction] = TypeAdapter(SimulationAction)


class ReferenceSimulationAdapter:
    """Translate canonical runtime domain actions to the reference engine."""

    def __init__(
        self,
        simulation: ReferenceSimulation | None = None,
        *,
        forbidden_actions: frozenset[str] = frozenset(),
    ) -> None:
        self.simulation = simulation or ReferenceSimulation()
        self.forbidden_actions = forbidden_actions
        self._initialized = False
        self._observation_sequence = 0

    async def initialize(self) -> None:
        self._initialized = True

    async def observe(self) -> Observation:
        self._require_initialized()
        self._observation_sequence += 1
        state = self.simulation.state
        state_payload = cast("dict[str, object]", state.model_dump(mode="json"))
        summary = (
            f"Tick {state.tick}: cash={state.cash:.2f}, population={state.population}, "
            f"infrastructure={state.infrastructure:.2f}, projects={len(state.active_projects)}, "
            f"paused={str(state.paused).lower()}, failed={str(state.failed).lower()}"
        )
        return Observation(
            sequence=self._observation_sequence,
            timestamp=datetime.now(UTC),
            tick=state.tick,
            summary=summary,
            state=state_payload,
        )

    async def available_actions(self) -> list[ActionDefinition]:
        self._require_initialized()
        return list(ACTION_DEFINITIONS)

    async def validate(self, action: Action) -> ValidationResult:
        self._require_initialized()
        if action.type in self.forbidden_actions:
            return invalid(f"Action '{action.type}' is forbidden by adapter constraints.")
        parsed = self._parse_action(action)
        if isinstance(parsed, ValidationResult):
            return parsed
        return self.simulation.validate(parsed)

    async def execute(self, action: Action) -> ExecutionResult:
        validation = await self.validate(action)
        if not validation.valid:
            return ExecutionResult(
                success=False,
                state_changed=False,
                cost=0.0,
                message=validation.message,
            )
        parsed = self._parse_action(action)
        if isinstance(parsed, ValidationResult):
            return ExecutionResult(
                success=False,
                state_changed=False,
                cost=0.0,
                message=parsed.message,
            )
        return self.simulation.execute(parsed)

    async def shutdown(self) -> None:
        self._initialized = False

    def snapshot(self) -> AdapterSnapshot:
        """Capture everything needed for deterministic adapter restoration."""
        state = cast("dict[str, JsonValue]", self.simulation.state.model_dump(mode="json"))
        return AdapterSnapshot(
            adapter_type="reference",
            simulation_schema_version=self.simulation.state.schema_version,
            observation_sequence=self._observation_sequence,
            seed=self.simulation.seed,
            state=state,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: AdapterSnapshot,
        *,
        forbidden_actions: frozenset[str] = frozenset(),
    ) -> "ReferenceSimulationAdapter":
        """Restore without observing or advancing the simulation."""
        if snapshot.adapter_type != "reference" or snapshot.schema_version != 1:
            msg = "unsupported reference adapter snapshot"
            raise ValueError(msg)
        if snapshot.simulation_schema_version != 1:
            msg = "unsupported reference simulation schema version"
            raise ValueError(msg)
        simulation = ReferenceSimulation.from_json(
            TypeAdapter(dict[str, JsonValue]).dump_json(snapshot.state).decode(),
            seed=snapshot.seed,
        )
        adapter = cls(simulation, forbidden_actions=forbidden_actions)
        adapter._observation_sequence = snapshot.observation_sequence
        return adapter

    def _parse_action(self, action: Action) -> SimulationAction | ValidationResult:
        payload: dict[str, object] = {"type": action.type, **action.parameters}
        try:
            return ACTION_ADAPTER.validate_python(payload, strict=True)
        except ValidationError as error:
            return invalid(f"Malformed action parameters: {error.errors()[0]['msg']}")

    def _require_initialized(self) -> None:
        if not self._initialized:
            msg = "Reference simulation adapter is not initialized."
            raise RuntimeError(msg)
