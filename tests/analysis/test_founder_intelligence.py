import json
from pathlib import Path

import pytest

from sim_pilot.analysis.contracts import AnalysisStatus, AnalysisType
from sim_pilot.analysis.evaluation import (
    FounderQuestionCategory,
    load_founder_intelligence_cases,
)

FIXTURE = Path("tests/fixtures/founder_intelligence_questions.json")


def test_catalog_has_unique_cases_all_categories_and_no_subjective_answers() -> None:
    cases = load_founder_intelligence_cases(FIXTURE)
    assert len(cases) == 45
    assert len({item.case_id for item in cases}) == len(cases)
    assert {item.category for item in cases} == set(FounderQuestionCategory)
    assert all(item.manual_rating is None for item in cases)
    assert all(item.revealed_nonobvious_information is None for item in cases)
    assert all(item.would_use_during_gameplay is None for item in cases)
    assert all(item.reviewer_notes is None for item in cases)


def test_catalog_has_at_least_thirty_supported_or_limited_cases() -> None:
    cases = load_founder_intelligence_cases(FIXTURE)
    supported_statuses = {AnalysisStatus.COMPLETED, AnalysisStatus.COMPLETED_WITH_LIMITATIONS}
    supported = [item for item in cases if supported_statuses.intersection(item.expected_statuses)]
    assert len(supported) == 37
    assert all(set(item.expected_analysis_types).issubset(set(AnalysisType)) for item in cases)


def test_comparison_cases_declare_compatible_status_expectations() -> None:
    cases = load_founder_intelligence_cases(FIXTURE)
    comparison_cases = [item for item in cases if item.requires_comparison]
    assert len(comparison_cases) == 10
    assert all(item.expected_statuses for item in comparison_cases)


def test_loader_rejects_duplicate_ids(tmp_path: Path) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload.append(payload[0])
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        load_founder_intelligence_cases(duplicate)
