"""Provider-independent simulation adapter contract."""

from typing import Protocol

from sim_pilot.domain import Action, ExecutionResult, Observation


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
