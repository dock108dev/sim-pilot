"""Runtime extension interfaces."""

from typing import Protocol

from sim_pilot.domain import Decision, Observation, Task


class DecisionProvider(Protocol):
    async def decide(self, task: Task, observation: Observation) -> Decision: ...
