"""Shared provider telemetry models independent of compiler and runtime semantics."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class ProviderTokenUsage(ProviderModel):
    input_tokens: int = Field(ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ProviderMetadata(ProviderModel):
    provider: str = Field(min_length=1)
    invocation_id: str | None = None
    provider_surface: str | None = None
    provider_version: str | None = None
    model: str | None = None
    request_id: str | None = None
    token_usage: ProviderTokenUsage | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    prompt_version: str | None = None
    validation_result: str | None = None
    telemetry_notes: tuple[str, ...] = ()
    started_at: datetime | None = None
    completed_at: datetime | None = None
    subprocess_exit_code: int | None = None
