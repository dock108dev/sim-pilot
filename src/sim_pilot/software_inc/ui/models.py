"""Strict Software Inc. synchronized UI observation and execution contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from sim_pilot.computer_control.models import DesktopFrame, InputGesture, ScreenPoint, WindowBounds
from sim_pilot.domain import Action
from sim_pilot.game_bridge.models import GameSnapshot


class UIModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SoftwareIncUIScene(StrEnum):
    GAMEPLAY_PAUSED = "gameplay_paused"
    GAMEPLAY_RUNNING = "gameplay_running"
    PAUSE_MENU = "pause_menu"
    MANAGEMENT_NAVIGATION = "management_navigation"
    MANAGE_TEAMS = "manage_teams"
    CREATE_TEAM_FORM = "create_team_form"
    HIRING_SETUP = "hiring_setup"
    APPLICANT_LIST = "applicant_list"
    HIRING_CONFIRMATION = "hiring_confirmation"
    HIRING_COMPLETE = "hiring_complete"
    EMPLOYEE_MANAGEMENT = "employee_management"
    EDUCATION = "education"
    ROLE_SELECTION = "role_selection"
    SERVER_MANAGEMENT = "server_management"
    BUILD_SEARCH = "build_search"
    BUILD_MODE = "build_mode"
    FURNITURE_PLACEMENT = "furniture_placement"
    ROOM_CONTEXT_MENU = "room_context_menu"
    ROOM_TEAM_SELECTION = "room_team_selection"
    CONTRACT_BROWSER = "contract_browser"
    CONTRACT_TEAM_SELECTION = "contract_team_selection"
    CONTRACT_REVIEW_SETUP = "contract_review_setup"
    CONTRACT_REVIEW_RESULT = "contract_review_result"
    PRODUCT_CONFIGURATION = "product_configuration"
    PRODUCT_TEAM_SELECTION = "product_team_selection"
    BLOCKING_MODAL = "blocking_modal"
    UNKNOWN = "unknown"


class ModalState(StrEnum):
    NONE = "none"
    BLOCKING = "blocking"
    UNKNOWN = "unknown"


class SoftwareIncUIAction(StrEnum):
    PAUSE = "pause"
    RESUME = "resume"
    OPEN_MANAGE_TEAMS = "open_manage_teams"
    CREATE_TEAM = "create_team"
    OBSERVE_APPLICANTS = "observe_applicants"
    HIRE_EMPLOYEE = "hire_employee"
    SET_TEAM_WORKING_HOURS = "set_team_working_hours"
    ASSIGN_EMPLOYEE_ROLE = "assign_employee_role"
    PREPARE_TEAM_WORKSTATION = "prepare_team_workstation"
    OPEN_CONTRACTS = "open_contracts"
    ACCEPT_CONTRACT = "accept_contract"
    REVIEW_CONTRACT = "review_contract"
    PROMOTE_CONTRACT = "promote_contract"
    RELEASE_CONTRACT = "release_contract"
    ADVANCE_CONTRACT = "advance_contract"
    START_EDUCATION = "start_education"
    ADVANCE_EDUCATION = "advance_education"
    CREATE_PRODUCT = "create_product"
    ADVANCE_PRODUCT = "advance_product"
    REVIEW_PRODUCT = "review_product"
    ITERATE_PRODUCT = "iterate_product"
    PROMOTE_PRODUCT = "promote_product"
    HOLD_PRODUCT = "hold_product"
    RESUME_PRODUCT = "resume_product"


class StaffingIntent(UIModel):
    schema_version: Literal[1] = 1
    action: Literal[
        SoftwareIncUIAction.CREATE_TEAM,
        SoftwareIncUIAction.OBSERVE_APPLICANTS,
        SoftwareIncUIAction.HIRE_EMPLOYEE,
    ]
    team_name: str = Field(min_length=1, max_length=64)
    role: Literal["Programmer"] | None = None
    maximum_monthly_salary: Decimal | None = Field(
        default=None, gt=0, max_digits=12, decimal_places=2
    )
    currency: Literal["USD"] = "USD"

    @field_validator("team_name")
    @classmethod
    def normalize_team_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("team name contains control characters")
        return normalized

    @model_validator(mode="after")
    def validate_hiring_fields(self) -> StaffingIntent:
        hiring = self.action in {
            SoftwareIncUIAction.OBSERVE_APPLICANTS,
            SoftwareIncUIAction.HIRE_EMPLOYEE,
        }
        if hiring != (self.role is not None and self.maximum_monthly_salary is not None):
            raise ValueError("hiring requests require exactly one role and monthly salary limit")
        return self


class ApplicantObservation(UIModel):
    schema_version: Literal[1] = 1
    applicant_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    role: str = Field(min_length=1, max_length=128)
    salary: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    salary_period: Literal["monthly"]
    currency: Literal["USD"] = "USD"
    wage_bracket: str = Field(min_length=1, max_length=64)
    display_index: int = Field(ge=0)
    selected_team: str = Field(max_length=64)
    available: bool
    source_bridge_sequence: int = Field(ge=1)


class HiringSearchObservation(UIModel):
    schema_version: Literal[1] = 1
    role: str = Field(min_length=1, max_length=128)
    wage_bracket: str = Field(min_length=1, max_length=64)
    one_time_cost: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    pool_text: str = Field(min_length=1, max_length=256)
    source_bridge_sequence: int = Field(ge=1)


class StaffingApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class StaffingPlan(UIModel):
    schema_version: Literal[1] = 1
    plan_id: UUID
    action: Literal[
        SoftwareIncUIAction.CREATE_TEAM,
        SoftwareIncUIAction.OBSERVE_APPLICANTS,
        SoftwareIncUIAction.HIRE_EMPLOYEE,
    ]
    game_session_id: str = Field(min_length=1, max_length=256)
    save_identity: str = Field(min_length=1, max_length=512)
    team_name: str = Field(min_length=1, max_length=64)
    normalized_team_name: str = Field(min_length=1, max_length=64)
    applicant: ApplicantObservation | None = None
    search: HiringSearchObservation | None = None
    maximum_monthly_salary: Decimal | None = Field(default=None, gt=0)
    expected_one_time_cost: Decimal = Field(default=Decimal("0"), ge=0)
    expected_monthly_cost: Decimal = Field(default=Decimal("0"), ge=0)
    expected_differences: tuple[str, ...]
    forbidden_differences: tuple[str, ...]
    source_frame_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_projection_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: AwareDatetime
    expires_at: AwareDatetime
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_plan_shape(self) -> StaffingPlan:
        is_hire = self.action is SoftwareIncUIAction.HIRE_EMPLOYEE
        is_search = self.action is SoftwareIncUIAction.OBSERVE_APPLICANTS
        if is_hire != (
            self.applicant is not None
            and self.maximum_monthly_salary is not None
            and self.expected_monthly_cost > 0
        ):
            raise ValueError("hire plan requires an applicant and bounded recurring cost")
        if is_search != (self.search is not None and self.expected_one_time_cost > 0):
            raise ValueError("applicant-search plan requires an observed one-time cost")
        if self.expected_one_time_cost > 0 and self.expected_monthly_cost > 0:
            raise ValueError("one approval cannot combine search and recurring costs")
        if self.expires_at <= self.created_at:
            raise ValueError("staffing plan expiration must follow creation")
        return self


class StaffingApproval(UIModel):
    schema_version: Literal[1] = 1
    id: UUID
    task_id: UUID
    action: Action
    status: StaffingApprovalStatus = StaffingApprovalStatus.PENDING
    created_at: AwareDatetime
    resolved_at: AwareDatetime | None = None
    plan_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_resolution(self) -> StaffingApproval:
        pending = self.status is StaffingApprovalStatus.PENDING
        if pending == (self.resolved_at is not None):
            raise ValueError("pending approval cannot be resolved; resolved approval requires time")
        return self


class StaffingResult(UIModel):
    schema_version: Literal[1] = 1
    intent: StaffingIntent
    plan: StaffingPlan | None = None
    approval: StaffingApproval | None = None
    before: SoftwareIncUIObservation
    after: SoftwareIncUIObservation
    gestures_sent: int = Field(ge=0)
    cycles: int = Field(ge=1)
    dry_run: bool
    verified: bool
    partial: bool = False
    expected_differences: tuple[str, ...] = ()
    unexpected_differences: tuple[str, ...] = ()
    message: str = Field(min_length=1, max_length=2048)
    completed_at: AwareDatetime


class StaffingTraceRecord(UIModel):
    schema_version: Literal[1] = 1
    operation_id: UUID
    action: SoftwareIncUIAction
    cycle: int = Field(ge=1)
    plan_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    approval_id: UUID | None = None
    observation_frame_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    bridge_sequence: int = Field(ge=1)
    scene: SoftwareIncUIScene
    projection_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_id: str | None = None
    gesture: InputGesture | None = None
    input_sent: bool
    verified: bool
    reason: str = Field(min_length=1, max_length=2048)
    recorded_at: AwareDatetime


class VisualTarget(UIModel):
    schema_version: Literal[1] = 1
    target_id: str = Field(min_length=1, max_length=256)
    source_frame_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    point: ScreenPoint | None = None
    region: WindowBounds | None = None
    scene: SoftwareIncUIScene
    projection_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    confidence: float = Field(ge=0, le=1)
    evidence: tuple[str, ...]
    expires_at: AwareDatetime


class SoftwareIncUIObservation(UIModel):
    schema_version: Literal[1] = 1
    semantic_before: GameSnapshot
    semantic_after: GameSnapshot
    frame: DesktopFrame
    scene: SoftwareIncUIScene
    modal_state: ModalState
    projection_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    targets: tuple[VisualTarget, ...]
    synchronization_started_at: AwareDatetime
    synchronization_completed_at: AwareDatetime
    synchronization_duration_seconds: float = Field(ge=0, le=15)
    semantic_capture_skew_seconds: float = Field(ge=0, le=15)

    @property
    def paused(self) -> bool:
        state = self.semantic_after.game_state
        return state.get("force_pause") is True or state.get("simulation_speed") in {"0", "0.0"}


class UIActionCapability(UIModel):
    schema_version: Literal[1] = 1
    action: SoftwareIncUIAction
    supported: bool
    offline_tested: bool
    live_verified: bool
    starting_scenes: tuple[SoftwareIncUIScene, ...]
    gesture_types: tuple[str, ...]
    semantic_postcondition: str
    visual_postcondition: str
    platform_boundary: str
    reason: str = Field(min_length=1, max_length=512)


class SoftwareIncUICapabilityCatalog(UIModel):
    schema_version: Literal[1] = 1
    game_version: Literal["1.8.41"] = "1.8.41"
    steam_build_id: Literal["23094975"] = "23094975"
    semantic_gameplay_actions: tuple[()] = ()
    capabilities: tuple[UIActionCapability, ...]


class SoftwareIncUIDoctorReport(UIModel):
    schema_version: Literal[1] = 1
    safe: bool
    process_id: int | None = Field(default=None, ge=1)
    window_id: str | None = None
    window_title: str | None = None
    window_bounds: WindowBounds | None = None
    display_scale: float | None = Field(default=None, gt=0, le=4)
    frontmost: bool | None = None
    exact_window_capture: bool
    screen_capture: bool
    accessibility_trusted: bool
    bridge_available: bool
    game_version: str | None = None
    steam_build_id: str | None = None
    reasons: tuple[str, ...]


class SoftwareIncUIDoResult(UIModel):
    schema_version: Literal[1] = 1
    action: SoftwareIncUIAction
    before: SoftwareIncUIObservation
    after: SoftwareIncUIObservation
    gestures_sent: int = Field(ge=0)
    cycles: int = Field(ge=1)
    dry_run: bool
    verified: bool
    expected_differences: tuple[str, ...] = ()
    unexpected_differences: tuple[str, ...] = ()
    message: str = Field(min_length=1, max_length=1024)
    completed_at: datetime


class SoftwareIncUITraceRecord(UIModel):
    schema_version: Literal[1] = 1
    action: SoftwareIncUIAction
    cycle: int = Field(ge=1)
    observation_frame_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    bridge_sequence: int = Field(ge=1)
    scene: SoftwareIncUIScene
    projection_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_id: str | None = None
    gesture: InputGesture | None = None
    input_sent: bool
    verified: bool
    reason: str = Field(min_length=1, max_length=1024)
    recorded_at: AwareDatetime


__all__ = [
    "ApplicantObservation",
    "HiringSearchObservation",
    "ModalState",
    "SoftwareIncUIAction",
    "SoftwareIncUIObservation",
    "SoftwareIncUIScene",
    "SoftwareIncUICapabilityCatalog",
    "SoftwareIncUIDoResult",
    "SoftwareIncUIDoctorReport",
    "SoftwareIncUITraceRecord",
    "StaffingApproval",
    "StaffingApprovalStatus",
    "StaffingIntent",
    "StaffingPlan",
    "StaffingResult",
    "StaffingTraceRecord",
    "UIActionCapability",
    "VisualTarget",
]
