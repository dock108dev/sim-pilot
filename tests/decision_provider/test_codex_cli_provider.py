"""Codex CLI decision provider through the shared fake process transport."""

import asyncio
import json
from pathlib import Path

import pytest

from sim_pilot.decision_provider import CodexCLIDecisionProvider, RecordingDecisionProvider
from sim_pilot.domain import Action, Decision, DecisionType
from sim_pilot.provider_support.codex_cli import CodexCLIClient
from sim_pilot.runtime.decision_context import DecisionProviderResult
from sim_pilot.runtime.decision_errors import DecisionSemanticValidationError
from tests.decision_provider.helpers import make_context
from tests.provider_support.codex_cli.helpers import FakeProcessRunner, capabilities


def _decision(action_type: str = "advance_time") -> Decision:
    return Decision(
        type=DecisionType.EXECUTE,
        reason="Advance one tick.",
        action=Action(
            type=action_type,
            parameters={"ticks": 1},
            expected_effect="Advance one tick.",
        ),
    )


def test_codex_decision_is_validated_and_returns_metadata(tmp_path: Path) -> None:
    runner = FakeProcessRunner(json.dumps({"payload": _decision().model_dump_json()}))
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    provider = CodexCLIDecisionProvider(model="gpt-5.6", client=client)

    result = asyncio.run(provider.decide(make_context()))

    assert result.decision == _decision()
    assert result.metadata.provider == "codex"
    assert result.metadata.provider_surface == "Codex CLI using authenticated ChatGPT access"
    assert "Do not run commands" in runner.stdin[0].decode()


@pytest.mark.parametrize("call_count", [1, 2, 10])
def test_consecutive_decision_calls_have_fresh_isolated_results(
    tmp_path: Path, call_count: int
) -> None:
    runner = FakeProcessRunner(json.dumps({"payload": _decision().model_dump_json()}))
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    provider = RecordingDecisionProvider(
        CodexCLIDecisionProvider(model="gpt-5.6", client=client),
        tmp_path / "recordings",
    )
    context = make_context()

    async def invoke() -> list[DecisionProviderResult]:
        return [await provider.decide(context) for _ in range(call_count)]

    results = asyncio.run(invoke())
    request_ids = [result.metadata.request_id for result in results]
    invocation_ids = [result.metadata.invocation_id for result in results]
    assert len(set(request_ids)) == call_count
    assert len(set(invocation_ids)) == call_count
    assert len(set(runner.working_directories)) == call_count
    assert len(tuple((tmp_path / "recordings").glob("*.json"))) == call_count


def test_codex_decision_cannot_invent_an_action(tmp_path: Path) -> None:
    runner = FakeProcessRunner(json.dumps({"payload": _decision("invent_train").model_dump_json()}))
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    provider = CodexCLIDecisionProvider(model="gpt-5.6", client=client)

    with pytest.raises(DecisionSemanticValidationError):
        asyncio.run(provider.decide(make_context()))


def test_codex_decision_metadata_flows_through_recording_wrapper(tmp_path: Path) -> None:
    runner = FakeProcessRunner(json.dumps({"payload": _decision().model_dump_json()}))
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    provider = RecordingDecisionProvider(
        CodexCLIDecisionProvider(model="gpt-5.6", client=client),
        tmp_path / "recordings",
    )
    asyncio.run(provider.decide(make_context()))

    recording = next((tmp_path / "recordings").iterdir()).read_text()
    assert '"provider": "codex"' in recording
    assert '"provider_version": "codex-cli 0.141.0"' in recording
