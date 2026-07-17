"""Opt-in decision recording security and failure behavior."""

import asyncio
from pathlib import Path

import pytest

from sim_pilot.decision_provider.models import DecisionRecording
from sim_pilot.decision_provider.providers.recording import RecordingDecisionProvider
from sim_pilot.decision_provider.providers.unconfigured import NoDecisionProviderConfigured
from sim_pilot.domain import Action, Decision, DecisionType
from sim_pilot.provider_metadata import ProviderMetadata, ProviderTokenUsage
from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult
from sim_pilot.runtime.decision_errors import (
    DecisionProviderNotConfiguredError,
    DecisionRecordingError,
)
from tests.decision_provider.helpers import make_context


class FakeProvider:
    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        del context
        return DecisionProviderResult(
            decision=Decision(
                type=DecisionType.EXECUTE,
                reason="Advance one tick.",
                action=Action(
                    type="advance_time",
                    parameters={"ticks": 1},
                    expected_effect="Advance one tick.",
                ),
            ),
            metadata=ProviderMetadata(
                provider="fake-openai",
                model="test-model",
                request_id="req_test",
                token_usage=ProviderTokenUsage(
                    input_tokens=10,
                    output_tokens=5,
                    total_tokens=15,
                ),
                latency_ms=12.5,
                prompt_version="decision-provider-v1",
                validation_result="valid",
            ),
        )


def test_recording_round_trip_permissions_and_redaction(tmp_path: Path) -> None:
    context = make_context(
        state={
            "cash": 500_000.0,
            "api_key": "secret-value",
            "nested": {"password": "also-secret"},
        }
    )

    async def scenario() -> DecisionProviderResult:
        return await RecordingDecisionProvider(FakeProvider(), tmp_path).decide(context)

    result = asyncio.run(scenario())
    paths = tuple(tmp_path.iterdir())
    assert len(paths) == 1
    assert paths[0].suffix == ".json"
    assert paths[0].stat().st_mode & 0o077 == 0
    recording = DecisionRecording.model_validate_json(paths[0].read_text())
    assert recording.response == result.decision
    assert recording.metadata == result.metadata
    state = recording.context["observation"]
    assert isinstance(state, dict)
    recorded_state = state["state"]
    assert isinstance(recorded_state, dict)
    assert recorded_state["api_key"] == "[REDACTED]"
    nested = recorded_state["nested"]
    assert isinstance(nested, dict)
    assert nested["password"] == "[REDACTED]"


def test_recording_failure_blocks_result_before_execution(tmp_path: Path) -> None:
    destination = tmp_path / "not-a-directory"
    destination.write_text("occupied")

    async def scenario() -> None:
        with pytest.raises(DecisionRecordingError, match="before execution"):
            await RecordingDecisionProvider(FakeProvider(), destination).decide(make_context())

    asyncio.run(scenario())


def test_unconfigured_provider_is_typed_and_offline_safe() -> None:
    async def scenario() -> None:
        with pytest.raises(DecisionProviderNotConfiguredError, match="--decision-provider"):
            await NoDecisionProviderConfigured().decide(make_context())

    asyncio.run(scenario())
