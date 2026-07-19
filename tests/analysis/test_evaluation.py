from pathlib import Path

from sim_pilot.analysis.evaluation import (
    FounderEvaluationResult,
    load_founder_questions,
)

FIXTURE = Path("tests/fixtures/analysis_founder_questions.json")


def test_founder_dataset_contains_at_least_thirty_unique_natural_questions() -> None:
    cases = load_founder_questions(FIXTURE)
    assert len(cases) >= 30
    assert len({item.id for item in cases}) == len(cases)
    assert len({item.question for item in cases}) == len(cases)
    assert {item.id.split("-", 1)[0] for item in cases}.issuperset(
        {"health", "vehicle", "station", "route", "coverage", "change", "unsupported"}
    )


def test_evaluation_record_requires_manual_rating_fields_before_conclusion() -> None:
    result = FounderEvaluationResult(case_id="health-01")
    assert result.manual_rating is None
    assert result.revealed_nonobvious_information is None
    assert result.reviewer_notes == ""
