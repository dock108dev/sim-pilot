"""Runtime extension interfaces."""

from typing import Protocol

from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult


class DecisionProvider(Protocol):
    async def decide(self, context: DecisionContext) -> DecisionProviderResult: ...
