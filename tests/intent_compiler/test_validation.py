"""Deterministic compiler semantic-validation failures."""

import asyncio
from decimal import Decimal

import pytest

from sim_pilot.domain import (
    AuthorityPolicy,
    Constraint,
    ConstraintType,
    Objective,
    ObjectiveType,
    TaskSpecification,
)
from sim_pilot.intent_compiler import IntentCompiler, ValidationStatus
from sim_pilot.intent_compiler.providers import ScriptedCompilerProvider
from tests.intent_compiler.helpers import response


def _compile(specification: TaskSpecification):
    return asyncio.run(
        IntentCompiler(ScriptedCompilerProvider([response(specification)])).compile("Test")
    )


@pytest.mark.parametrize(
    ("resource", "target", "code"),
    (
        ("gold", 10, "invalid_resource"),
        ("cash", -1, "invalid_threshold"),
        ("infrastructure", 101, "impossible_objective"),
        ("maintenance_level", 2, "impossible_objective"),
    ),
)
def test_invalid_resources_thresholds_and_impossible_objectives(
    resource: str, target: float, code: str
) -> None:
    spec = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Test objective.",
            parameters={"resource": resource, "target": target},
        ),
        authority=AuthorityPolicy(),
    )
    result = _compile(spec)
    assert result.report.validation_status is ValidationStatus.INVALID
    assert code in {error.code for error in result.report.validation_errors}


def test_invalid_actions_and_contradictory_constraints() -> None:
    spec = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.REACH_RESOURCE,
            description="Reach cash.",
            parameters={"resource": "cash", "target": 600_000},
        ),
        constraints=(
            Constraint(
                type=ConstraintType.ALLOWED_ACTION,
                description="Only loans.",
                parameters={"actions": ["take_loan"]},
            ),
            Constraint(
                type=ConstraintType.FORBIDDEN_ACTION,
                description="No loans.",
                parameters={"action": "take_loan"},
            ),
        ),
        authority=AuthorityPolicy(approval_actions=("teleport",)),
    )
    result = _compile(spec)
    codes = {error.code for error in result.report.validation_errors}
    assert {"invalid_action", "contradictory_constraints"} <= codes


def test_duplicate_incompatible_allowed_rules_and_authority_conflict() -> None:
    spec = TaskSpecification(
        objective=Objective(
            type=ObjectiveType.RUN_UNTIL,
            description="Run until cash falls.",
            parameters={"resource": "cash", "target": 100_000, "direction": "below"},
        ),
        constraints=(
            Constraint(
                type=ConstraintType.ALLOWED_ACTION,
                description="Only advance.",
                parameters={"actions": ["advance_time"]},
            ),
            Constraint(
                type=ConstraintType.ALLOWED_ACTION,
                description="Only repair.",
                parameters={"actions": ["repair"]},
            ),
            Constraint(
                type=ConstraintType.RESOURCE_FLOOR,
                description="Keep reserve.",
                parameters={"resource": "cash", "floor": 100_000},
            ),
        ),
        authority=AuthorityPolicy(
            maximum_single_spend=Decimal("50"),
            maximum_total_spend=Decimal("100"),
            approval_actions=("take_loan",),
            forbidden_actions=("take_loan",),
        ),
    )
    result = _compile(spec)
    codes = {error.code for error in result.report.validation_errors}
    assert {"contradictory_authority", "contradictory_constraints"} <= codes
