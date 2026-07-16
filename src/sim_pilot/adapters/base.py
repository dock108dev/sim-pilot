"""Provider-independent simulation adapter contract."""

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.domain import Action, ExecutionResult, Observation
from sim_pilot.domain.models import JsonValue


class AdapterSnapshot(BaseModel):
    """Storage-independent adapter restoration payload."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    adapter_type: str = Field(min_length=1)
    simulation_schema_version: int = Field(ge=1)
    observation_sequence: int = Field(ge=0)
    seed: str
    state: dict[str, JsonValue]


class AdapterValidation(Protocol):
    """Structural validation result required by the runtime."""

    valid: bool
    message: str
    estimated_cost: float


class SimulationAdapter(Protocol):
    """Contract implemented by runtime-facing simulation adapters."""

    async def initialize(self) -> None: ...

    async def observe(self) -> Observation: ...

    async def validate(self, action: Action) -> AdapterValidation: ...

    async def execute(self, action: Action) -> ExecutionResult: ...

    async def shutdown(self) -> None: ...


@runtime_checkable
class CheckpointableSimulationAdapter(Protocol):
    """Optional adapter capability required for process-level restoration."""

    def snapshot(self) -> AdapterSnapshot: ...
