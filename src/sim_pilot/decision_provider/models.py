"""Recording and evaluation models for runtime decision providers."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sim_pilot.domain import Decision, DecisionType
from sim_pilot.domain.models import JsonValue
from sim_pilot.provider_metadata import ProviderMetadata


class DecisionProviderModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1


class DecisionRecording(DecisionProviderModel):
    id: UUID
    captured_at: AwareDatetime
    context: dict[str, JsonValue]
    response: Decision
    metadata: ProviderMetadata
    validation_result: str = Field(min_length=1)


class DecisionEvaluationFixture(DecisionProviderModel):
    name: str = Field(min_length=1)
    context: dict[str, JsonValue]
    candidate: Decision
    expected_allowed_types: tuple[DecisionType, ...]
    forbidden_types: tuple[DecisionType, ...] = ()
    expected_action: str | None = None
    expected_valid: bool


def utc_timestamp() -> datetime:
    from datetime import UTC

    return datetime.now(UTC)
