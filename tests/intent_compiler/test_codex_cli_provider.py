"""Codex CLI compiler provider through the shared fake process transport."""

import asyncio
import json
from pathlib import Path

import pytest

from sim_pilot.intent_compiler import CompilerProviderResult, IntentCompiler, ValidationStatus
from sim_pilot.intent_compiler.providers import (
    CodexCLICompilerProvider,
    RecordingCompilerProvider,
)
from sim_pilot.provider_support.codex_cli import CodexCLIClient
from tests.intent_compiler.helpers import response, valid_specification
from tests.provider_support.codex_cli.helpers import FakeProcessRunner, capabilities


def test_codex_compiler_returns_canonical_response_and_metadata(tmp_path: Path) -> None:
    expected = response(valid_specification())
    runner = FakeProcessRunner(json.dumps({"payload": expected.model_dump_json()}))
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    provider = CodexCLICompilerProvider(model="gpt-5.6", client=client)

    result = asyncio.run(IntentCompiler(provider).compile("Reach one million cash."))

    assert result.report.validation_status is ValidationStatus.VALID
    assert result.specification == valid_specification()
    assert "Player instruction:\nReach one million cash." in runner.stdin[0].decode()
    assert "Do not inspect files" in runner.stdin[0].decode()


@pytest.mark.parametrize("call_count", [1, 2, 10])
def test_consecutive_compiler_calls_have_fresh_isolated_results(
    tmp_path: Path, call_count: int
) -> None:
    expected = response(valid_specification())
    runner = FakeProcessRunner(json.dumps({"payload": expected.model_dump_json()}))
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    provider = RecordingCompilerProvider(
        CodexCLICompilerProvider(model="gpt-5.6", client=client),
        tmp_path / "recordings",
    )

    async def invoke() -> list[CompilerProviderResult]:
        return [await provider.compile("Reach one million cash.") for _ in range(call_count)]

    results = asyncio.run(invoke())
    request_ids = [result.metadata.request_id for result in results]
    invocation_ids = [result.metadata.invocation_id for result in results]
    assert len(set(request_ids)) == call_count
    assert len(set(invocation_ids)) == call_count
    assert len(set(runner.working_directories)) == call_count
    assert len(tuple((tmp_path / "recordings").glob("*.json"))) == call_count


def test_codex_compiler_schema_round_trips_canonical_response(tmp_path: Path) -> None:
    expected = response(valid_specification())
    runner = FakeProcessRunner(json.dumps({"payload": expected.model_dump_json()}))
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        preserve_debug_directory=True,
        runner=runner,
        capabilities=capabilities(),
    )
    provider = CodexCLICompilerProvider(model="gpt-5.6", client=client)
    asyncio.run(provider.compile("Reach one million cash."))

    schema_path = runner.working_directories[0] / "output-schema.json"
    assert schema_path.is_file()
    assert '"additionalProperties": false' in schema_path.read_text()
    import shutil

    shutil.rmtree(runner.working_directories[0])


def test_codex_compiler_metadata_flows_through_recording_wrapper(tmp_path: Path) -> None:
    expected = response(valid_specification())
    runner = FakeProcessRunner(json.dumps({"payload": expected.model_dump_json()}))
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    provider = RecordingCompilerProvider(
        CodexCLICompilerProvider(model="gpt-5.6", client=client),
        tmp_path / "recordings",
    )
    asyncio.run(provider.compile("Reach one million cash."))

    recording = next((tmp_path / "recordings").iterdir()).read_text()
    assert '"provider": "codex"' in recording
    assert '"provider_version": "codex-cli 0.141.0"' in recording
