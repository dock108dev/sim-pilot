"""Opt-in live decision-provider schema and runtime validation."""

import asyncio
import os

import pytest

from sim_pilot.config import decision_model, decision_timeout_seconds
from sim_pilot.decision_provider import OpenAIDecisionProvider
from sim_pilot.runtime.decision_validation import validate_provider_decision
from tests.decision_provider.helpers import make_context

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("SIM_PILOT_LIVE_DECISION") != "1" or not os.getenv("OPENAI_API_KEY"),
        reason="set SIM_PILOT_LIVE_DECISION=1 and OPENAI_API_KEY to run live decision tests",
    ),
]


def test_live_openai_decision_is_schema_and_runtime_valid() -> None:
    async def scenario() -> None:
        context = make_context()
        result = await OpenAIDecisionProvider(
            model=decision_model(),
            timeout_seconds=decision_timeout_seconds(),
        ).decide(context)
        fingerprint = validate_provider_decision(result.decision, context)
        print(
            {
                "schema_valid": True,
                "runtime_valid": True,
                "decision": result.decision.model_dump(mode="json"),
                "latency_ms": result.metadata.latency_ms,
                "token_usage": (
                    None
                    if result.metadata.token_usage is None
                    else result.metadata.token_usage.model_dump(mode="json")
                ),
                "failure_category": None,
                "fingerprint": fingerprint,
            }
        )

    asyncio.run(scenario())
