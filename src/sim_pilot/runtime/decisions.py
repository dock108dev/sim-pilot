"""Deterministic scripted decision provider."""

from collections.abc import Iterable

from sim_pilot.domain import Decision
from sim_pilot.provider_metadata import ProviderMetadata
from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult


class ScriptedDecisionExhaustedError(RuntimeError):
    """Raised when a scripted provider has no decision remaining."""


class ScriptedDecisionProvider:
    """Return exactly one prebuilt decision per request."""

    def __init__(self, decisions: Iterable[Decision]) -> None:
        self._decisions = tuple(decisions)
        self.request_count = 0

    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        del context
        if self.request_count >= len(self._decisions):
            msg = "scripted decision provider exhausted"
            raise ScriptedDecisionExhaustedError(msg)
        decision = self._decisions[self.request_count]
        self.request_count += 1
        return DecisionProviderResult(
            decision=decision,
            metadata=ProviderMetadata(
                provider="scripted",
                prompt_version="decision-provider-v1",
                validation_result="scripted",
            ),
        )
