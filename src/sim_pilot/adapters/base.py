"""Provider-independent simulation adapter contract."""

from enum import StrEnum
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


class ActionParameterType(StrEnum):
    INTEGER = "integer"
    NUMBER = "number"
    STRING = "string"
    BOOLEAN = "boolean"


class ActionParameterDefinition(BaseModel):
    """Exact provider-facing schema for one adapter action parameter."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    type: ActionParameterType
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    allowed_values: tuple[JsonValue, ...] = ()


class ActionDefinition(BaseModel):
    """Runtime-facing description and exact parameter schema for an adapter action."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    type: str = Field(min_length=1)
    parameters: tuple[ActionParameterDefinition, ...] = ()
    description: str = Field(min_length=1)

    @property
    def parameter_names(self) -> tuple[str, ...]:
        return tuple(parameter.name for parameter in self.parameters)


class AdapterValidation(Protocol):
    """Structural validation result required by the runtime."""

    valid: bool
    message: str
    estimated_cost: float


class SimulationAdapter(Protocol):
    """Contract implemented by runtime-facing simulation adapters."""

    async def initialize(self) -> None: ...

    async def observe(self) -> Observation: ...

    async def available_actions(self) -> list[ActionDefinition]: ...

    async def validate(self, action: Action) -> AdapterValidation: ...

    async def execute(self, action: Action) -> ExecutionResult: ...

    async def shutdown(self) -> None: ...


@runtime_checkable
class CheckpointableSimulationAdapter(Protocol):
    """Optional adapter capability required for process-level restoration."""

    def snapshot(self) -> AdapterSnapshot: ...
