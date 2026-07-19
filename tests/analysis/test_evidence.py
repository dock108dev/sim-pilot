import pytest

from sim_pilot.analysis.contracts import AnalysisSubjectType, AnalysisType, EvidenceConfidence
from sim_pilot.analysis.errors import AnalysisInputError
from sim_pilot.analysis.evidence import (
    evidence_confidence,
    field_evidence,
    observer_company,
    stable_finding_id,
)
from sim_pilot.domain.world import Company
from tests.analysis.helpers import snapshot


def test_evidence_and_finding_identity_are_stable() -> None:
    value = snapshot()
    first = stable_finding_id(
        AnalysisType.FINANCIAL_SUMMARY,
        value.metadata.snapshot_id,
        "cash_position",
        ("company-1",),
    )
    second = stable_finding_id(
        AnalysisType.FINANCIAL_SUMMARY,
        value.metadata.snapshot_id,
        "cash_position",
        ("company-1",),
    )
    evidence = field_evidence(
        value,
        entity_type=AnalysisSubjectType.COMPANY,
        entity_id="company-1",
        field="cash",
        value=100,
    )

    assert first == second
    assert evidence.snapshot_id == value.metadata.snapshot_id
    assert evidence.observed_value == 100


def test_observer_company_is_explicit_and_ambiguity_fails() -> None:
    assert observer_company(snapshot()).id == "company-1"
    ambiguous = snapshot(observer_company_id=None).model_copy(
        update={
            "companies": (
                Company(id="company-1", name="One", cash=1, loan=0),
                Company(id="company-2", name="Two", cash=2, loan=0),
            )
        }
    )
    with pytest.raises(AnalysisInputError, match="ambiguous"):
        observer_company(ambiguous)


def test_confidence_comes_from_evidence_quality() -> None:
    value = snapshot()
    assert evidence_confidence(value, category="vehicles") is EvidenceConfidence.HIGH
    assert evidence_confidence(value, category="routes", inferred=True) is EvidenceConfidence.MEDIUM
    assert (
        evidence_confidence(snapshot(complete=False), category="vehicles") is EvidenceConfidence.LOW
    )
