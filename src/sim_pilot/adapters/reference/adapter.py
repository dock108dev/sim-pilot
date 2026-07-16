"""Adapter boundary between the runtime and reference simulation."""

from datetime import UTC, datetime
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from sim_pilot.adapters.base import AdapterSnapshot
from sim_pilot.domain import Action, ExecutionResult, Observation
from sim_pilot.domain.models import JsonValue
from sim_pilot.reference_simulation import ReferenceSimulation, SimulationAction, ValidationResult
from sim_pilot.reference_simulation.validation import invalid


class ActionDefinition(BaseModel):
    """A runtime-facing description of one supported action."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    type: str = Field(min_length=1)
    parameter_names: tuple[str, ...] = ()
    description: str = Field(min_length=1)


ACTION_DEFINITIONS = (
    ActionDefinition(
        type="advance_time",
        parameter_names=("ticks",),
        description="Advance the simulation by one or more ticks.",
    ),
    ActionDefinition(
        type="build_housing",
        parameter_names=("units",),
        description="Start a housing construction project.",
    ),
    ActionDefinition(
        type="build_power",
        parameter_names=("capacity",),
        description="Start a power construction project.",
    ),
    ActionDefinition(
        type="repair",
        parameter_names=("amount",),
        description="Repair infrastructure immediately.",
    ),
    ActionDefinition(
        type="set_maintenance",
        parameter_names=("level",),
        description="Set the recurring maintenance level.",
    ),
    ActionDefinition(
        type="take_loan",
        parameter_names=("amount",),
        description="Take a loan within the debt limits.",
    ),
    ActionDefinition(
        type="repay_loan",
        parameter_names=("amount",),
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
