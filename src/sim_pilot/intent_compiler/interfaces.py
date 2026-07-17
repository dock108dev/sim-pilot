"""Provider-independent Intent Compiler interface."""

from typing import Protocol

from sim_pilot.intent_compiler.models import CompilerResponse


class CompilerProvider(Protocol):
    async def compile(self, instruction: str) -> CompilerResponse: ...
