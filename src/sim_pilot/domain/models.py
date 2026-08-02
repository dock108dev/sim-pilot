"""Strict Pydantic models for the Sim Pilot domain."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from sim_pilot.domain.types import (
    AdapterId,
    ConstraintType,
    DecisionType,
    ObjectiveType,
    TaskStatus,
)

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type AdapterType = AdapterId
type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


class DomainModel(BaseModel):
    """Common validation rules for data crossing runtime boundaries."""

    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: int = Field(default=1, ge=1)


class Objective(DomainModel):
    """A typed objective and its simulation-independent arguments."""

    type: ObjectiveType
    description: NonEmptyString
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class Constraint(DomainModel):
    """A typed operational restriction and its arguments."""

    type: ConstraintType
    description: NonEmptyString
    parameters: dict[str, JsonValue] = Field(default_factory=dict)


class AuthorityPolicy(DomainModel):
    """Limits on actions that the runtime may execute autonomously."""

    maximum_single_spend: Decimal | None = Field(default=None, ge=0)
    maximum_total_spend: Decimal | None = Field(default=None, ge=0)
    approval_actions: tuple[NonEmptyString, ...] = ()
    forbidden_actions: tuple[NonEmptyString, ...] = ()

    @model_validator(mode="after")
    def validate_spend_limits(self) -> AuthorityPolicy:
        """Reject a single-action limit that can exceed the total limit."""
        if (
            self.maximum_single_spend is not None
            and self.maximum_total_spend is not None
            and self.maximum_single_spend > self.maximum_total_spend
        ):
            msg = "maximum_single_spend cannot exceed maximum_total_spend"
            raise ValueError(msg)
        return self


class TaskSpecification(DomainModel):
    """The compiled, structured definition of delegated work."""

    adapter_type: AdapterType = AdapterId.REFERENCE
    objective: Objective
    constraints: tuple[Constraint, ...] = ()
    authority: AuthorityPolicy
    notifications: tuple[NonEmptyString, ...] = ()
    stop_conditions: tuple[NonEmptyString, ...] = ()

    @field_validator("adapter_type", mode="before")
    @classmethod
    def parse_adapter_type(cls, value: object) -> object:
        """Accept persisted string identifiers while retaining a closed enum contract."""
        if isinstance(value, str):
            return AdapterId(value)
        return value


class Observation(DomainModel):
    """An immutable snapshot of simulation state."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    sequence: int = Field(ge=0)
    timestamp: datetime
    tick: int = Field(ge=0)
    summary: NonEmptyString
    state: dict[str, object]


class Action(DomainModel):
    """A proposed simulation action, including its expected effect and cost."""

    type: NonEmptyString
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    expected_effect: NonEmptyString
    estimated_cost: Decimal = Field(default=Decimal(0), ge=0)


class Decision(DomainModel):
    """The next decision selected for a task cycle."""

    type: DecisionType
    reason: NonEmptyString
    action: Action | None = None

    @model_validator(mode="after")
    def validate_action_presence(self) -> Decision:
        """Require an action only for decisions that concern execution."""
        action_required = self.type in {
            DecisionType.EXECUTE,
            DecisionType.APPROVAL_REQUIRED,
        }
        if action_required and self.action is None:
            msg = f"an action is required for a {self.type.value} decision"
            raise ValueError(msg)
        if not action_required and self.action is not None:
            msg = f"an action is not allowed for a {self.type.value} decision"
            raise ValueError(msg)
        return self


class ExecutionResult(DomainModel):
    """The adapter-reported outcome of one attempted action."""

    success: bool
    state_changed: bool
    cost: float = Field(ge=0)
    message: NonEmptyString


class Task(DomainModel):
    """A delegated task and its current lifecycle state."""

    id: UUID
    status: TaskStatus
    specification: TaskSpecification
    sequence: int = Field(default=0, ge=0)
    total_spend: Decimal = Field(default=Decimal(0), ge=0)
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @model_validator(mode="after")
    def validate_timestamps(self) -> Task:
        """Ensure task updates cannot predate task creation."""
        if self.updated_at < self.created_at:
            msg = "updated_at cannot be earlier than created_at"
            raise ValueError(msg)
        return self
