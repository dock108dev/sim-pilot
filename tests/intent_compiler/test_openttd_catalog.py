"""Environment-specific compiler capability validation."""

from sim_pilot.domain import (
    AuthorityPolicy,
    Constraint,
    ConstraintType,
    Objective,
    ObjectiveType,
    TaskSpecification,
)
from sim_pilot.intent_compiler.prompt import OPENTTD_CAPABILITIES
from sim_pilot.intent_compiler.validation import validate_specification


def test_openttd_catalog_accepts_server_name_equality() -> None:
    specification = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.RUN_UNTIL,
            description="Set the server name.",
            parameters={
                "resource": "server_name",
                "target": "Sim Pilot",
                "direction": "equal",
            },
        ),
        constraints=(
            Constraint(
                type=ConstraintType.ALLOWED_ACTION,
                description="Only set the server name.",
                parameters={"actions": ["set_server_name"]},
            ),
        ),
        authority=AuthorityPolicy(),
    )

    assert validate_specification(specification, OPENTTD_CAPABILITIES) == ()


def test_openttd_catalog_rejects_route_construction_action() -> None:
    specification = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Build a route.",
            parameters={"resource": "cash", "target": 1_000_000},
        ),
        constraints=(
            Constraint(
                type=ConstraintType.ALLOWED_ACTION,
                description="Build tracks.",
                parameters={"actions": ["build_route"]},
            ),
        ),
        authority=AuthorityPolicy(),
    )

    errors = validate_specification(specification, OPENTTD_CAPABILITIES)

    assert any(error.code == "invalid_action" for error in errors)
