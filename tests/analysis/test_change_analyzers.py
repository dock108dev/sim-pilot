from sim_pilot.analysis.analyzers.changes import (
    AnomalyDetectionAnalyzer,
    EntitySummaryAnalyzer,
    PriorityReviewAnalyzer,
    WorldChangesAnalyzer,
)
from sim_pilot.analysis.contracts import (
    AnalysisRequest,
    AnalysisSubjectType,
    AnalysisType,
    FindingKind,
    FindingSeverity,
)
from sim_pilot.domain.world import (
    Company,
    CoverageChanged,
    CoverageStatus,
    EntityRemoved,
    FieldChanged,
    Vehicle,
)
from tests.analysis.helpers import snapshot


def test_world_changes_classifies_material_and_data_quality_changes() -> None:
    current = snapshot().model_copy(
        update={
            "changes_from_snapshot_id": "snapshot-previous",
            "changes": (
                FieldChanged(
                    entity_type="company",
                    entity_id="company-1",
                    field="cash",
                    before=1_000_000,
                    after=800_000,
                ),
                EntityRemoved(entity_type="vehicle", entity_id="vehicle-1"),
                CoverageChanged(
                    category="vehicles",
                    before=CoverageStatus.AVAILABLE,
                    after=CoverageStatus.PARTIAL,
                ),
            ),
        }
    )
    result = WorldChangesAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.WORLD_CHANGES, question="Changes?"),
        current,
        None,
    )
    assert len(result.findings) == 3
    assert all(
        item.evidence[0].comparison_snapshot_id == "snapshot-previous" for item in result.findings
    )
    assert any(item.kind is FindingKind.DATA_QUALITY for item in result.findings)
    assert all(item.severity is FindingSeverity.WARNING for item in result.findings)


def test_anomaly_thresholds_and_comparison_evidence() -> None:
    previous = snapshot(
        "snapshot-previous",
        game_date=10,
        company=Company(id="company-1", name="Company", cash=1_000_000, loan=0),
    )
    current = snapshot(company=Company(id="company-1", name="Company", cash=700_000, loan=60_000))
    result = AnomalyDetectionAnalyzer().analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.ANOMALY_DETECTION,
            question="Anything unusual?",
            comparison_snapshot_id="snapshot-previous",
        ),
        current,
        previous,
    )
    assert {item.finding_code for item in result.findings} == {
        "cash_drop_anomaly",
        "debt_increase_anomaly",
    }
    assert all(
        item.evidence[0].comparison_snapshot_id == "snapshot-previous" for item in result.findings
    )


def test_entity_summary_reports_missing_ids_without_invention() -> None:
    result = EntitySummaryAnalyzer().analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.ENTITY_SUMMARY,
            question="Summarize these companies",
            subject_type=AnalysisSubjectType.COMPANY,
            subject_ids=("company-1", "missing"),
        ),
        snapshot(),
        None,
    )
    assert len(result.findings) == 1
    assert result.findings[0].evidence[0].entity_id == "company-1"
    assert "Entity missing was not observed." in result.limitations


def test_priority_review_exposes_priority_score() -> None:
    loss = Vehicle(
        id="vehicle-1",
        type="road",
        name="Loss",
        age_days=100,
        profit_this_year=-100,
        profit_last_year=-100,
        running_state="running",
        coordinates=None,
        in_depot=False,
        owner_id="company-1",
    )
    current = snapshot(
        company=Company(
            id="company-1",
            name="Company",
            cash=-1,
            loan=100,
            income=0,
            expenses=-1,
        ),
        vehicles=(loss,),
    )
    result = PriorityReviewAnalyzer().analyze(
        AnalysisRequest(
            analysis_type=AnalysisType.PRIORITY_REVIEW,
            question="What next?",
            maximum_findings=2,
        ),
        current,
        None,
    )
    assert len(result.findings) == 2
    assert result.findings[0].metric_name == "priority_score"
    assert result.findings[0].metric_value == 100
    assert result.findings[0].analysis_type is AnalysisType.PRIORITY_REVIEW
