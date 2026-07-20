import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sim_pilot.analysis.analyzers import AnalyzerResult
from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    EvidenceConfidence,
    FindingKind,
    FindingSeverity,
)
from sim_pilot.analysis.evidence import field_evidence
from sim_pilot.analysis.registry import AnalyzerRegistry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.analysis.session import AnalysisSessionStore
from sim_pilot.domain.world import WorldSnapshot
from tests.analysis.helpers import snapshot


class SessionAnalyzer:
    analysis_type = AnalysisType.FINANCIAL_SUMMARY

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del request, comparison
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED,
            answer="Observed company cash.",
            findings=(
                AnalysisFinding(
                    finding_id="finding-cash",
                    finding_code="cash",
                    analysis_type=self.analysis_type,
                    kind=FindingKind.OBSERVED_FACT,
                    severity=FindingSeverity.INFORMATIONAL,
                    title="Observed cash",
                    summary="Cash is 100.",
                    metric_name="cash",
                    metric_value=100,
                    confidence=EvidenceConfidence.HIGH,
                    evidence=(
                        field_evidence(
                            current,
                            entity_type=AnalysisSubjectType.COMPANY,
                            entity_id="company-1",
                            field="cash",
                            value=100,
                        ),
                    ),
                ),
            ),
        )


def response(world: WorldSnapshot):
    return AnalysisService(
        AnalyzerRegistry((SessionAnalyzer(),)),
        clock=lambda: datetime(2026, 7, 20, tzinfo=UTC),
    ).analyze(
        AnalysisRequest(analysis_type=AnalysisType.FINANCIAL_SUMMARY, question="Cash?"),
        world,
    )


def test_session_store_round_trips_owner_only_records(tmp_path: Path) -> None:
    world = snapshot()
    store = AnalysisSessionStore(tmp_path / "sessions")
    record = store.save(response(world), world)

    assert store.load() == record
    assert store.load(record.analysis_id) == record
    assert stat.S_IMODE((tmp_path / "sessions").stat().st_mode) == 0o700
    assert all(
        stat.S_IMODE(item.stat().st_mode) == 0o600 for item in (tmp_path / "sessions").iterdir()
    )

    context = store.compiler_context(world)
    assert context.prior_analysis_id == record.analysis_id
    assert len(context.focus_entities) == 1
    assert context.focus_entities[0].subject_type is AnalysisSubjectType.COMPANY


def test_session_context_is_dropped_when_save_identity_changes(tmp_path: Path) -> None:
    world = snapshot()
    store = AnalysisSessionStore(tmp_path / "sessions")
    store.save(response(world), world)
    changed = world.model_copy(
        update={
            "metadata": world.metadata.model_copy(
                update={"save_generation": world.metadata.save_generation + 1}
            )
        }
    )

    context = store.compiler_context(changed)

    assert context.prior_analysis_id is None
    assert context.focus_entities == ()


def test_session_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = AnalysisSessionStore(tmp_path)
    with pytest.raises(ValueError, match="invalid format"):
        store.load("../../secret")
