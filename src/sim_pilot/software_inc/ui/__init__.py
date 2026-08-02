"""Verified visible-UI control for Software Inc."""

from .controller import execute_ui_action, parse_ui_action
from .models import (
    ApplicantObservation,
    HiringSearchObservation,
    ModalState,
    SoftwareIncUIAction,
    SoftwareIncUICapabilityCatalog,
    SoftwareIncUIDoctorReport,
    SoftwareIncUIDoResult,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    StaffingApproval,
    StaffingIntent,
    StaffingPlan,
    StaffingResult,
)
from .observer import SoftwareIncUIObserver
from .office import (
    OfficeIntent,
    OfficeOperationResult,
    OfficePurchaseApproval,
    SupportedEmployeeRole,
    TeamOfficeReadiness,
    parse_office_intent,
    project_team_readiness,
)
from .office_controller import execute_office_intent
from .service import diagnose_ui
from .staffing import parse_staffing_intent
from .staffing_controller import execute_staffing_intent
from .workstation import (
    FurnitureCatalogItem,
    WorkstationApproval,
    WorkstationIntent,
    WorkstationLineItem,
    WorkstationOperationResult,
    WorkstationPlan,
    build_workstation_plan,
    parse_workstation_intent,
    select_workstation_catalog,
)
from .workstation_controller import execute_workstation_intent

__all__ = [
    "ApplicantObservation",
    "HiringSearchObservation",
    "FurnitureCatalogItem",
    "ModalState",
    "OfficeIntent",
    "OfficeOperationResult",
    "OfficePurchaseApproval",
    "SoftwareIncUIAction",
    "SoftwareIncUICapabilityCatalog",
    "SoftwareIncUIDoResult",
    "SoftwareIncUIDoctorReport",
    "SoftwareIncUIObservation",
    "SoftwareIncUIObserver",
    "SoftwareIncUIScene",
    "StaffingIntent",
    "StaffingApproval",
    "StaffingPlan",
    "StaffingResult",
    "SupportedEmployeeRole",
    "TeamOfficeReadiness",
    "WorkstationApproval",
    "WorkstationIntent",
    "WorkstationLineItem",
    "WorkstationOperationResult",
    "WorkstationPlan",
    "build_workstation_plan",
    "diagnose_ui",
    "execute_ui_action",
    "execute_staffing_intent",
    "execute_office_intent",
    "execute_workstation_intent",
    "parse_office_intent",
    "parse_staffing_intent",
    "parse_ui_action",
    "parse_workstation_intent",
    "project_team_readiness",
    "select_workstation_catalog",
]
