from datetime import UTC, datetime

import pytest

from sim_pilot.analysis.analyzers import AnalyzerResult
from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    EvidenceConfidence,
    FindingKind,
    FindingSeverity,
)
from sim_pilot.analysis.errors import (
    AnalyzerRegistrationError,
    AnalyzerResultError,
)
from sim_pilot.analysis.evidence import field_evidence
from sim_pilot.analysis.registry import AnalyzerRegistry, default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.domain.world import WorldSnapshot
from tests.analysis.helpers import snapshot


class FakeFinancialAnalyzer:
    analysis_type = AnalysisType.FINANCIAL_SUMMARY

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del request, comparison
        findings = tuple(
            AnalysisFinding(
                finding_id=f"finding-{index}",
                finding_code=f"cash-{index}",
                analysis_type=self.analysis_type,
                kind=FindingKind.OBSERVED_FACT,
                severity=FindingSeverity.INFORMATIONAL,
                title=f"Cash finding {index}",
                summary=f"Observed cash finding {index}.",
                metric_name="cash",
                metric_value=index,
                confidence=EvidenceConfidence.HIGH,
                evidence=(
                    field_evidence(
                        current,
                        entity_type=AnalysisSubjectType.COMPANY,
                        entity_id="company-1",
                        field="cash",
                        value=index,
                    ),
                ),
                recommendation_ids=(f"recommendation-{index}",),
            )
            for index in (1, 2)
        )
        recommendations = tuple(
            AnalysisRecommendation(
                recommendation_id=f"recommendation-{index}",
                title=f"Inspect {index}",
                rationale="Review the observed value.",
                priority=index,
                supporting_finding_ids=(f"finding-{index}",),
            )
            for index in (1, 2)
        )
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED,
            answer="Two deterministic findings were produced.",
            findings=findings,
            recommendations=recommendations,
        )


def request(maximum_findings: int = 1) -> AnalysisRequest:
    return AnalysisRequest(
        analysis_type=AnalysisType.FINANCIAL_SUMMARY,
        question="Summarize company finances.",
        maximum_findings=maximum_findings,
    )


def test_registry_rejects_duplicate_and_missing_analyzers() -> None:
    registry = AnalyzerRegistry((FakeFinancialAnalyzer(),))
    with pytest.raises(AnalyzerRegistrationError, match="duplicate"):
        registry.register(FakeFinancialAnalyzer())
    with pytest.raises(AnalyzerRegistrationError, match="no analyzer"):
        registry.get(AnalysisType.VEHICLE_PERFORMANCE)


def test_default_registry_covers_the_closed_catalog() -> None:
    assert set(default_analyzer_registry().registered_types) == set(AnalysisType)


def test_service_validates_truncates_and_preserves_reference_integrity() -> None:
    service = AnalysisService(
        AnalyzerRegistry((FakeFinancialAnalyzer(),)),
        clock=lambda: datetime(2026, 7, 19, tzinfo=UTC),
    )

    response = service.analyze(request(), snapshot())

    assert response.status is AnalysisStatus.COMPLETED_WITH_LIMITATIONS
    assert [item.finding_id for item in response.findings] == ["finding-1"]
    assert [item.recommendation_id for item in response.recommendations] == ["recommendation-1"]
    assert response.findings[0].recommendation_ids == ("recommendation-1",)
    assert "companies coverage is partial." in response.limitations


class InvalidEvidenceAnalyzer(FakeFinancialAnalyzer):
    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        result = super().analyze(request, current, comparison)
        invalid = result.findings[0].model_copy(
            update={
                "evidence": (
                    result.findings[0]
                    .evidence[0]
                    .model_copy(update={"snapshot_id": "unknown-snapshot"}),
                )
            }
        )
        return result.model_copy(update={"findings": (invalid,)})


def test_service_rejects_unknown_evidence_references() -> None:
    service = AnalysisService(AnalyzerRegistry((InvalidEvidenceAnalyzer(),)))
    with pytest.raises(AnalyzerResultError, match="unknown snapshot"):
        service.analyze(request(), snapshot())
