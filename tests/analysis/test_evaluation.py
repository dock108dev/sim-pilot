from pathlib import Path

from sim_pilot.analysis.evaluation import (
    FounderEvaluationResult,
    FounderSampleRating,
    load_founder_questions,
    load_founder_results,
)

FIXTURE = Path("tests/fixtures/analysis_founder_questions.json")
RESULTS = Path("docs/evaluation/phase8b-founder-results.json")


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


def test_live_founder_rating_is_recorded() -> None:
    results = load_founder_results(RESULTS)
    assert len(results) == 1
    assert results[0].manual_rating == "acceptable"
    assert results[0].revealed_nonobvious_information == "partially"


def test_bounded_founder_sample_preserves_owner_authored_values() -> None:
    rating = FounderSampleRating(
        case_id="company-health-001",
        manual_rating="acceptable",
        revealed_nonobvious_information="partially",
        would_use_during_gameplay="maybe",
        identified_right_subject="yes",
        most_important_finding_first="yes",
        evidence_sufficient="partially",
        limitation_understandable="yes",
        too_verbose="yes",
        faster_than_manual_inspection="maybe",
        next_question="Which parts of the fleet are least profitable?",
        reviewer_notes="Trustworthy but generic.",
    )
    assert rating.too_verbose == "yes"
    assert rating.manual_rating == "acceptable"
