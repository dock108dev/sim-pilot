"""Provider metadata and opt-in recording behavior."""

import asyncio
import stat
from pathlib import Path

import pytest

from sim_pilot.intent_compiler import (
    CompilerProviderResult,
    CompilerRecording,
)
from sim_pilot.intent_compiler.errors import CompilerProviderError
from sim_pilot.intent_compiler.providers import (
    NoProviderConfigured,
    RecordingCompilerProvider,
    ScriptedCompilerProvider,
)
from sim_pilot.provider_metadata import ProviderMetadata, ProviderTokenUsage
from tests.intent_compiler.helpers import response, valid_specification


def test_scripted_provider_returns_typed_metadata() -> None:
    async def scenario() -> None:
        result = await ScriptedCompilerProvider([response(valid_specification())]).compile(
            "Reach one million cash."
        )
        assert result.response.specification == valid_specification()
        assert result.metadata == ProviderMetadata(provider="scripted")

    asyncio.run(scenario())


def test_no_provider_configured_fails_without_hosted_access() -> None:
    async def scenario() -> None:
        with pytest.raises(CompilerProviderError, match="--provider openai"):
            await NoProviderConfigured().compile("Reach one million cash.")

    asyncio.run(scenario())


def test_recording_provider_writes_complete_atomic_json(tmp_path: Path) -> None:
    tmp_path.chmod(0o755)
    provider_result = CompilerProviderResult(
        response=response(valid_specification()),
        metadata=ProviderMetadata(
            provider="example",
            model="example-model",
            token_usage=ProviderTokenUsage(
                input_tokens=100,
                output_tokens=40,
                total_tokens=140,
            ),
        ),
    )

    class ExampleProvider:
        async def compile(self, instruction: str) -> CompilerProviderResult:
            assert instruction == "Reach one million cash."
            return provider_result

    async def scenario() -> None:
        returned = await RecordingCompilerProvider(ExampleProvider(), tmp_path).compile(
            "Reach one million cash."
        )
        assert returned == provider_result

    asyncio.run(scenario())
    paths = tuple(tmp_path.iterdir())
    assert len(paths) == 1
    assert paths[0].suffix == ".json"
    recording = CompilerRecording.model_validate_json(paths[0].read_text())
    assert recording.prompt_version == "intent-compiler-v3"
    assert "Sim Pilot Intent Compiler" in recording.prompt
    assert recording.instruction == "Reach one million cash."
    assert recording.response == provider_result.response
    assert recording.provider_metadata == provider_result.metadata
    assert recording.latency_ms >= 0
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert paths[0].stat().st_mode & 0o077 == 0
