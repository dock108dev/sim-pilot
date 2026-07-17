"""Deterministic validation of untrusted structured decisions."""

from decimal import Decimal

import pytest

from sim_pilot.domain import Action, Decision, DecisionType
from sim_pilot.runtime.decision_context import PendingRestrictions
from sim_pilot.runtime.decision_errors import DecisionSemanticValidationError
from sim_pilot.runtime.decision_validation import validate_provider_decision
from tests.decision_provider.helpers import make_context


def _execute(action_type: str, **parameters: object) -> Decision:
    return Decision(
        type=DecisionType.EXECUTE,
        reason="Execute one advertised action.",
        action=Action(
            type=action_type,
            parameters=parameters,  # type: ignore[arg-type]
            expected_effect="State changes as advertised.",
        ),
    )


def test_valid_action_returns_stable_fingerprint() -> None:
    decision = _execute("advance_time", ticks=1)
    first = validate_provider_decision(decision, make_context())
    second = validate_provider_decision(decision, make_context())
    assert first == second
    assert len(first) == 64


@pytest.mark.parametrize(
    ("decision", "message"),
    (
        (_execute("invent_train", count=1), "not advertised"),
        (_execute("advance_time"), "missing parameters"),
        (_execute("advance_time", ticks=1, extra=2), "unknown parameters"),
        (_execute("advance_time", ticks=1.5), "must be integer"),
        (_execute("advance_time", ticks=0), "at least 1"),
        (_execute("set_maintenance", level=0.25), "not an allowed value"),
        (_execute("take_loan", amount=9_999), "at least 10000"),
        (_execute("take_loan", amount=500_001), "at most 500000"),
        (
            Decision(type=DecisionType.COMPLETE, reason="Looks complete."),
            "not confirmed",
        ),
    ),
)
def test_invalid_decisions_are_not_repaired(decision: Decision, message: str) -> None:
    with pytest.raises(DecisionSemanticValidationError, match=message):
        validate_provider_decision(decision, make_context())


def test_completion_is_valid_only_when_evaluator_confirms_it() -> None:
    decision = Decision(type=DecisionType.COMPLETE, reason="Evaluator confirms completion.")
    assert validate_provider_decision(decision, make_context(complete=True)) == "no-action"


def test_non_finite_cost_is_rejected() -> None:
    decision = _execute("advance_time", ticks=1)
    assert decision.action is not None
    invalid = decision.model_copy(
        update={"action": decision.action.model_copy(update={"estimated_cost": Decimal("NaN")})}
    )
    with pytest.raises(DecisionSemanticValidationError, match="finite"):
        validate_provider_decision(invalid, make_context())


def test_previously_rejected_or_denied_action_cannot_repeat_unchanged() -> None:
    context = make_context().model_copy(
        update={
            "pending_restrictions": PendingRestrictions(
                rejected_actions=("advance_time",),
                denied_actions=("take_loan",),
            )
        }
    )
    with pytest.raises(DecisionSemanticValidationError, match="previously rejected"):
        validate_provider_decision(_execute("advance_time", ticks=1), context)
