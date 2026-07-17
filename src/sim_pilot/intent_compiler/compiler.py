"""Provider-independent natural-language compilation pipeline."""

from sim_pilot.intent_compiler.interfaces import CompilerProvider
from sim_pilot.intent_compiler.models import (
    CompilationResult,
    CompilerReport,
    ValidationStatus,
)
from sim_pilot.intent_compiler.prompt import PROMPT_VERSION
from sim_pilot.intent_compiler.validation import (
    missing_specification_error,
    validate_specification,
)


class IntentCompiler:
    def __init__(self, provider: CompilerProvider) -> None:
        self._provider = provider

    async def compile(self, instruction: str) -> CompilationResult:
        normalized = instruction.strip()
        if not normalized:
            raise ValueError("instruction must not be empty")
        response = await self._provider.compile(normalized)
        errors = validate_specification(response.specification)
        if errors:
            status = ValidationStatus.INVALID
        elif response.unsupported_requests:
            status = ValidationStatus.UNSUPPORTED
        elif response.ambiguities:
            status = ValidationStatus.CLARIFICATION_REQUIRED
        elif response.specification is None:
            status = ValidationStatus.INVALID
            errors = (
                *errors,
                missing_specification_error(),
            )
        else:
            status = ValidationStatus.VALID
        report = CompilerReport(
            prompt_version=PROMPT_VERSION,
            validation_status=status,
            assumptions=response.assumptions,
            warnings=response.warnings,
            unsupported_requests=response.unsupported_requests,
            ambiguities=response.ambiguities,
            validation_errors=errors,
        )
        return CompilationResult(
            instruction=normalized,
            specification=response.specification if status is ValidationStatus.VALID else None,
            report=report,
        )
