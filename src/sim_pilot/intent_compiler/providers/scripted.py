"""Deterministic compiler provider for tests and offline examples."""

from collections.abc import Iterable

from sim_pilot.intent_compiler.errors import CompilerProviderError
from sim_pilot.intent_compiler.models import (
    CompilerProviderMetadata,
    CompilerProviderResult,
    CompilerResponse,
)


class ScriptedCompilerProvider:
    def __init__(self, responses: Iterable[CompilerResponse]) -> None:
        self._responses = tuple(responses)
        self.request_count = 0

    async def compile(self, instruction: str) -> CompilerProviderResult:
        if not instruction.strip():
            raise ValueError("instruction must not be empty")
        if self.request_count >= len(self._responses):
            raise CompilerProviderError("scripted compiler provider exhausted")
        response = self._responses[self.request_count]
        self.request_count += 1
        return CompilerProviderResult(
            response=response,
            metadata=CompilerProviderMetadata(provider="scripted"),
        )
