"""Snapshots for domain interfaces frozen by RFC-001."""

from sim_pilot.domain import Action, Decision, Observation, TaskSpecification


def test_task_specification_contract() -> None:
    assert tuple(TaskSpecification.model_fields) == (
        "schema_version",
        "adapter_type",
        "objective",
        "constraints",
        "authority",
        "notifications",
        "stop_conditions",
    )


def test_observation_contract() -> None:
    assert tuple(Observation.model_fields) == (
        "schema_version",
        "sequence",
        "timestamp",
        "tick",
        "summary",
        "state",
    )


def test_action_contract() -> None:
    assert tuple(Action.model_fields) == (
        "schema_version",
        "type",
        "parameters",
        "expected_effect",
        "estimated_cost",
    )


def test_decision_contract() -> None:
    assert tuple(Decision.model_fields) == (
        "schema_version",
        "type",
        "reason",
        "action",
    )
