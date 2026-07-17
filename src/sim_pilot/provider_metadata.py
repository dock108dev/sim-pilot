"""Shared provider telemetry models independent of compiler and runtime semantics."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class ProviderTokenUsage(ProviderModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ProviderMetadata(ProviderModel):
    provider: str = Field(min_length=1)
    model: str | None = None
    request_id: str | None = None
    token_usage: ProviderTokenUsage | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    prompt_version: str | None = None
    validation_result: str | None = None
