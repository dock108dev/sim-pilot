"""Typed Prompt 7 contracts for one controlled Software Inc. product."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class ProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ProductStage(StrEnum):
    CONFIGURATION = "configuration"
    DESIGN = "design"
    ALPHA = "alpha"
    BETA = "beta"


class ProductWorkflowStatus(StrEnum):
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    ACTIVE = "active"
    HELD = "held"
    BETA_REACHED = "beta_reached"
    BLOCKED = "blocked"
    FAILED = "failed"


class ProductCommitment(StrEnum):
    CREATE = "create"
    REVIEW = "review"
    ITERATE = "iterate"
    PROMOTE = "promote"


class ProductFeatureObservation(ProductModel):
    feature_id: str
    name: str
    specialization: str
    dependencies: tuple[str, ...]
    development_time: Decimal = Field(ge=0)
    code_art_ratio: Decimal = Field(ge=0)
    server_requirement: Decimal = Field(ge=0)
    unlocked: bool


class ProductTypeObservation(ProductModel):
    name: str
    description: str
    categories: tuple[str, ...]
    unlocked: bool
    in_house: bool
    os_specific: bool
    optimal_development_time: Decimal = Field(ge=0)


class ProductCategoryObservation(ProductModel):
    product_type: str
    name: str
    description: str
    ideal_price: Decimal = Field(ge=0)
    is_default: bool
    unlocked: bool


class ProductOperatingSystemObservation(ProductModel):
    product_id: str
    name: str
    userbase: int = Field(ge=0)
    release_date: str
    selected: bool


class ProductConfiguration(ProductModel):
    name: str = Field(min_length=1, max_length=64)
    product_type: str
    category: str
    features: tuple[str, ...] = Field(min_length=1)
    operating_systems: tuple[str, ...] = Field(min_length=1)
    design_teams: tuple[str, ...] = Field(min_length=1)
    development_teams: tuple[str, ...] = Field(min_length=1)
    price: Decimal = Field(ge=0)
    server_requirement: Decimal = Field(ge=0)
    expected_development_months: Decimal = Field(gt=0)
    team_issue: str = ""


class ProductRunway(ProductModel):
    observed_cash: Decimal
    minimum_cash_reserve: Decimal = Field(ge=0)
    observed_monthly_payroll: Decimal = Field(ge=0)
    observed_monthly_infrastructure: Decimal = Field(ge=0)
    conservative_months: Decimal = Field(gt=0)
    conservative_recurring_cost: Decimal = Field(ge=0)
    known_one_time_cost: Decimal = Field(ge=0)
    projected_cash_after: Decimal
    forecast_revenue_included: Literal[False] = False


class TeamSuitability(ProductModel):
    team_name: str
    employee_count: int = Field(ge=0)
    programmer_skill: Decimal = Field(ge=0)
    designer_skill: Decimal = Field(ge=0)
    artist_skill: Decimal = Field(ge=0)
    relevant_specializations: tuple[str, ...]
    role_specializations: tuple[str, ...]
    active_work: tuple[str, ...]
    suitable: bool
    reasons: tuple[str, ...]


class ProductRecommendation(ProductModel):
    schema_version: Literal[1] = 1
    recommendation_id: str = Field(pattern=r"^product-recommendation:[0-9a-f]{24}$")
    game_session_id: str
    save_identity: str
    source_bridge_sequence: int = Field(ge=1)
    capability_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration: ProductConfiguration
    runway: ProductRunway
    team: TeamSuitability
    recommended: bool
    reasons: tuple[str, ...]
    material_unknowns: tuple[str, ...]
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def validate_expiration(self) -> ProductRecommendation:
        if self.expires_at <= self.created_at:
            raise ValueError("product recommendation expiration must follow creation")
        return self


class ProductApproval(ProductModel):
    schema_version: Literal[1] = 1
    approval_id: UUID
    workflow_id: UUID
    commitment: ProductCommitment
    action_summary: str = Field(min_length=1, max_length=2048)
    product_name: str
    stage_before: ProductStage
    expected_stage_after: ProductStage
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_cash: Decimal
    projected_cash_after: Decimal
    minimum_cash_reserve: Decimal = Field(ge=0)
    one_time_cost: Decimal = Field(ge=0)
    approved: bool | None = None
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> ProductApproval:
        if (self.approved is None) != (self.resolved_at is None):
            raise ValueError("pending approval cannot be resolved; resolution requires a decision")
        return self


class ProductWorkflow(ProductModel):
    schema_version: Literal[1] = 1
    workflow_id: UUID
    game_session_id: str
    save_identity: str
    product_name: str
    product_type: str
    category: str
    features: tuple[str, ...]
    operating_systems: tuple[str, ...]
    team_name: str
    price: Decimal = Field(ge=0)
    minimum_cash_reserve: Decimal = Field(ge=0)
    initial_cash: Decimal
    projected_cash_after: Decimal
    stage: ProductStage
    status: ProductWorkflowStatus
    work_item_id: str | None = None
    held: bool = False
    iteration: int = Field(ge=0)
    progress: Decimal = Field(ge=0)
    review_accuracy: Decimal | None = Field(default=None, ge=0)
    review_score: Decimal | None = Field(default=None, ge=0)
    pending_approval: ProductApproval | None = None
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    last_bridge_sequence: int = Field(ge=1)
    created_at: AwareDatetime
    updated_at: AwareDatetime


class ProductCycleEvent(ProductModel):
    schema_version: Literal[1] = 1
    event_id: UUID
    workflow_id: UUID
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1, max_length=64)
    bridge_sequence: int = Field(ge=1)
    stage_before: ProductStage
    stage_after: ProductStage
    action: str | None = None
    input_sent: bool
    verified: bool
    detail: str = Field(min_length=1, max_length=2048)
    recorded_at: AwareDatetime


class ProductOperationResult(ProductModel):
    schema_version: Literal[1] = 1
    workflow: ProductWorkflow | None = None
    recommendation: ProductRecommendation | None = None
    event: ProductCycleEvent | None = None
    gestures_sent: int = Field(ge=0)
    verified: bool
    partial: bool
    message: str = Field(min_length=1, max_length=2048)
    completed_at: datetime


__all__ = [
    "ProductApproval",
    "ProductCategoryObservation",
    "ProductCommitment",
    "ProductConfiguration",
    "ProductCycleEvent",
    "ProductFeatureObservation",
    "ProductModel",
    "ProductOperationResult",
    "ProductOperatingSystemObservation",
    "ProductRecommendation",
    "ProductRunway",
    "ProductStage",
    "ProductTypeObservation",
    "ProductWorkflow",
    "ProductWorkflowStatus",
    "TeamSuitability",
]
