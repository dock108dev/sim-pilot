"""Offline fixture harness for deterministic decision validation."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from sim_pilot.decision_provider.models import DecisionEvaluationFixture
from sim_pilot.runtime.decision_context import DecisionContext
from sim_pilot.runtime.decision_errors import DecisionSemanticValidationError
from sim_pilot.runtime.decision_validation import validate_provider_decision


def load_evaluation_fixtures(path: Path) -> tuple[DecisionEvaluationFixture, ...]:
    content = path.read_text(encoding="utf-8")
    raw = json.loads(content)
    if not isinstance(raw, list):
        raise ValueError("decision evaluation fixture file must contain a list")
    return tuple(TypeAdapter(list[DecisionEvaluationFixture]).validate_json(content))


def evaluate_fixture(fixture: DecisionEvaluationFixture) -> bool:
    context = DecisionContext.model_validate_json(json.dumps(fixture.context))
    try:
        validate_provider_decision(fixture.candidate, context)
    except DecisionSemanticValidationError:
        return not fixture.expected_valid
    if not fixture.expected_valid:
        return False
    if fixture.candidate.type not in fixture.expected_allowed_types:
        return False
    if fixture.candidate.type in fixture.forbidden_types:
        return False
    return fixture.expected_action is None or (
        fixture.candidate.action is not None
        and fixture.candidate.action.type == fixture.expected_action
    )
