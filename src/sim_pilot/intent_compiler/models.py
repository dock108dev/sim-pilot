"""Strict structured-output, provider, and reporting models for intent compilation."""

from enum import StrEnum
from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from sim_pilot.domain import TaskSpecification
from sim_pilot.provider_metadata import ProviderMetadata, ProviderTokenUsage


class CompilerModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class ValidationStatus(StrEnum):
    VALID = "valid"
    CLARIFICATION_REQUIRED = "clarification_required"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"


class CompilerCapabilityCatalog(CompilerModel):
    """Environment-specific names accepted by deterministic compiler validation."""

    name: str = Field(min_length=1)
    adapter_type: str = Field(min_length=1)
    resources: tuple[str, ...]
    actions: tuple[str, ...]
    string_resources: tuple[str, ...] = ()
    project_types: tuple[str, ...] = ()


class CompilerValidationError(CompilerModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    path: str | None = None


class CompilerResponse(CompilerModel):
    """Provider-produced data; semantic validity is not trusted."""

    specification: TaskSpecification | None
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...]
    unsupported_requests: tuple[str, ...]
    ambiguities: tuple[str, ...]


CompilerTokenUsage = ProviderTokenUsage
CompilerProviderMetadata = ProviderMetadata


class CompilerProviderResult(CompilerModel):
    """One provider response plus non-semantic request metadata."""

    response: CompilerResponse
    metadata: CompilerProviderMetadata


class CompilerRecording(CompilerModel):
    """Local diagnostic record emitted only by an explicit recording wrapper."""

    id: UUID
    captured_at: AwareDatetime
    prompt_version: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    instruction: str = Field(min_length=1)
    latency_ms: float = Field(ge=0)
    provider_metadata: CompilerProviderMetadata
    response: CompilerResponse


class CompilerReport(CompilerModel):
    prompt_version: str = Field(min_length=1)
    validation_status: ValidationStatus
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    unsupported_requests: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    validation_errors: tuple[CompilerValidationError, ...] = ()


class CompilationResult(CompilerModel):
    instruction: str = Field(min_length=1)
    specification: TaskSpecification | None
    report: CompilerReport

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        is_valid = self.report.validation_status is ValidationStatus.VALID
        if is_valid != (self.specification is not None):
            raise ValueError("only a valid compilation may expose a task specification")
        return self
