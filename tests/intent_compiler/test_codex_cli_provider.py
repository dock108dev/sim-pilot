"""Codex CLI compiler provider through the shared fake process transport."""

import asyncio
import json
from pathlib import Path

from sim_pilot.intent_compiler import IntentCompiler, ValidationStatus
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
    assert "Player instruction:\nReach one million cash." in runner.commands[0][-1]
    assert "Do not inspect files" in runner.commands[0][-1]


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
