"""Enumerated domain values defined by the Month 1 design."""

from enum import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle states available to a task."""

    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ObjectiveType(StrEnum):
    """Objective variants supported by the Month 1 design."""

    REACH_RESOURCE = "reach_resource"
    MAINTAIN_RESOURCE = "maintain_resource"
    COMPLETE_PROJECT = "complete_project"
    RUN_UNTIL = "run_until"


class ConstraintType(StrEnum):
    """Constraint variants supported by the Month 1 design."""

    MAXIMUM_SPEND = "maximum_spend"
    MINIMUM_RESERVE = "minimum_reserve"
    ALLOWED_ACTION = "allowed_action"
    FORBIDDEN_ACTION = "forbidden_action"
    RESOURCE_FLOOR = "resource_floor"


class DecisionType(StrEnum):
    """Outcomes available from a decision engine."""

    EXECUTE = "execute"
    WAIT = "wait"
    COMPLETE = "complete"
    APPROVAL_REQUIRED = "approval_required"
    BLOCKED = "blocked"
