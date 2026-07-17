"""Opt-in local JSON recording decorator for compiler providers."""

from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from sim_pilot.intent_compiler.interfaces import CompilerProvider
from sim_pilot.intent_compiler.models import CompilerProviderResult, CompilerRecording
from sim_pilot.intent_compiler.prompt import INTENT_COMPILER_PROMPT, PROMPT_VERSION


class RecordingCompilerProvider:
    """Record successful structured provider exchanges without changing semantics."""

    def __init__(
        self,
        provider: CompilerProvider,
        directory: Path,
        *,
        prompt: str = INTENT_COMPILER_PROMPT,
    ) -> None:
        self._provider = provider
        self._directory = directory
        self._prompt = prompt

    async def compile(self, instruction: str) -> CompilerProviderResult:
        started = perf_counter()
        result = await self._provider.compile(instruction)
        recording = CompilerRecording(
            id=uuid4(),
            captured_at=datetime.now(UTC),
            prompt_version=PROMPT_VERSION,
            prompt=self._prompt,
            instruction=instruction,
            latency_ms=(perf_counter() - started) * 1000,
            provider_metadata=result.metadata,
            response=result.response,
        )
        self._write(recording)
        return result

    def _write(self, recording: CompilerRecording) -> None:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        stem = f"{recording.captured_at.strftime('%Y%m%dT%H%M%S%fZ')}-{recording.id}"
        destination = self._directory / f"{stem}.json"
        temporary = self._directory / f".{stem}.tmp"
        try:
            temporary.write_text(recording.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
