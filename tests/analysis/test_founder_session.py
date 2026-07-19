from datetime import UTC, datetime
from pathlib import Path

from sim_pilot.analysis.compiler import AnalysisCompilation, ScriptedAnalysisCompiler
from sim_pilot.analysis.contracts import (
    AnalysisExplanation,
    AnalysisExplanationStatement,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    ExplanationClaimType,
)
from sim_pilot.analysis.evaluation import FounderIntelligenceCase, FounderQuestionCategory
from sim_pilot.analysis.explanation import ScriptedExplanationProvider
from sim_pilot.analysis.founder_session import run_founder_session
from tests.analysis.helpers import snapshot


def test_founder_session_records_three_passes_and_empty_review_fields(tmp_path: Path) -> None:
    case = FounderIntelligenceCase(
        case_id="company-health-001",
        category=FounderQuestionCategory.COMPANY_HEALTH,
        question="How healthy is my company?",
        expected_analysis_types=(AnalysisType.COMPANY_HEALTH,),
        expected_statuses=(AnalysisStatus.COMPLETED, AnalysisStatus.COMPLETED_WITH_LIMITATIONS),
        required_evidence_types=(AnalysisSubjectType.COMPANY,),
    )
    request = AnalysisRequest(
        analysis_type=AnalysisType.COMPANY_HEALTH,
        question=case.question,
    )
    explanation = AnalysisExplanation(
        statements=(
            AnalysisExplanationStatement(
                claim_type=ExplanationClaimType.SUMMARY,
                text="The deterministic findings describe company health.",
            ),
        )
    )
    world = snapshot()
    manifest = run_founder_session(
        cases=(case,),
        current=world,
        comparison=world,
        compiler=ScriptedAnalysisCompiler((AnalysisCompilation(request=request),)),
        explanation_provider=ScriptedExplanationProvider((explanation,)),
        compiler_metadata=lambda: None,
        explanation_metadata=lambda: None,
        output_directory=tmp_path,
        explanation_case_ids=frozenset({case.case_id}),
        clock=lambda: datetime(2026, 7, 20, tzinfo=UTC),
    )
    assert manifest.deterministic_case_count == 1
    assert manifest.compiler_case_count == 1
    assert manifest.explanation_case_count == 1
    review = (tmp_path / "manual-review.json").read_text(encoding="utf-8")
    assert '"manual_rating": null' in review
    assert (tmp_path / "pass-a-deterministic.json").is_file()
    assert (tmp_path / "pass-b-codex-compiler.json").is_file()
    assert (tmp_path / "pass-c-codex-explanation.json").is_file()
