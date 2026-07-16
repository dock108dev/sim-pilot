"""Deterministic task lifecycle transitions."""

from sim_pilot.domain import TaskStatus

TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.RUNNING, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset(
        {
            TaskStatus.COMPLETED,
            TaskStatus.BLOCKED,
            TaskStatus.FAILED,
            TaskStatus.WAITING_FOR_APPROVAL,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.WAITING_FOR_APPROVAL: frozenset(
        {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.BLOCKED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}


def transition(current: TaskStatus, target: TaskStatus) -> TaskStatus:
    """Return target when transition is allowed, otherwise fail deterministically."""
    if target not in TRANSITIONS[current]:
        msg = f"invalid task transition: {current.value} -> {target.value}"
        raise ValueError(msg)
    return target
