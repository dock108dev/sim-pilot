"""Offline decision evaluation fixture harness."""

from pathlib import Path

from sim_pilot.decision_provider.evaluation import evaluate_fixture, load_evaluation_fixtures


def test_all_required_decision_scenarios_are_present_and_validated() -> None:
    fixtures = load_evaluation_fixtures(
        Path(__file__).parents[1] / "fixtures" / "decision_evaluation.json"
    )
    assert len(fixtures) >= 25
    assert {fixture.name for fixture in fixtures} >= {
        "cash_target_progression",
        "project_construction",
        "infrastructure_repair",
        "maintenance_adjustment",
        "power_shortage",
        "housing_shortage",
        "loan_prohibited",
        "reserve_constraint",
        "approval_threshold",
        "total_spend_limit",
        "paused_simulation",
        "failed_simulation",
        "false_completion_temptation",
        "repeated_action",
        "repeated_state",
        "prior_execution_failure",
        "denied_action",
        "no_valid_action",
        "task_already_complete",
        "ambiguous_strategy",
        "project_already_active",
        "project_capacity_limit",
        "insufficient_cash",
        "repayment_decision",
        "wait_decision",
    }
    assert all(evaluate_fixture(fixture) for fixture in fixtures)
