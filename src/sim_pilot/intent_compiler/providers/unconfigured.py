"""Safe default provider that never performs hosted work implicitly."""

from typing import NoReturn

from sim_pilot.intent_compiler.errors import CompilerProviderError


class NoProviderConfigured:
    async def compile(self, instruction: str) -> NoReturn:
        if not instruction.strip():
            raise ValueError("instruction must not be empty")
        raise CompilerProviderError(
            "no compiler provider configured; select --provider openai for a hosted request"
        )
