"""Typed compiler fixtures for tests."""

from sim_pilot.domain import (
    AuthorityPolicy,
    Objective,
    ObjectiveType,
    TaskSpecification,
)
from sim_pilot.intent_compiler import CompilerResponse


def valid_specification() -> TaskSpecification:
    return TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Reach one million cash.",
            parameters={"resource": "cash", "target": 1_000_000},
        ),
        authority=AuthorityPolicy(),
    )


def response(
    specification: TaskSpecification | None = None,
    *,
    assumptions: tuple[str, ...] = (),
    warnings: tuple[str, ...] = (),
    unsupported_requests: tuple[str, ...] = (),
    ambiguities: tuple[str, ...] = (),
) -> CompilerResponse:
    return CompilerResponse(
        specification=specification,
        assumptions=assumptions,
        warnings=warnings,
        unsupported_requests=unsupported_requests,
        ambiguities=ambiguities,
    )
