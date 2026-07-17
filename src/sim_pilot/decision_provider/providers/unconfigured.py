"""Offline-safe runtime decision provider used until selection is explicit."""

from typing import NoReturn

from sim_pilot.runtime.decision_context import DecisionContext
from sim_pilot.runtime.decision_errors import DecisionProviderNotConfiguredError


class NoDecisionProviderConfigured:
    async def decide(self, context: DecisionContext) -> NoReturn:
        del context
        raise DecisionProviderNotConfiguredError(
            "no decision provider configured; select --decision-provider openai "
            "for a hosted request"
        )
