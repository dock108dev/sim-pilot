"""Explicitly gated read-only OpenTTD and Codex analysis checks."""

import asyncio
import os

import pytest

from sim_pilot.analysis.compiler import AnalysisCompilation, ScriptedAnalysisCompiler
from sim_pilot.analysis.contracts import AnalysisRequest, AnalysisType
from sim_pilot.analysis.query import AnalysisQueryService
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.analysis_provider import CodexExplanationProvider
from sim_pilot.cli import capture_openttd_world_snapshot
from sim_pilot.config import codex_model, codex_timeout_seconds


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("SIM_PILOT_LIVE_OPENTTD_ANALYSIS") != "1",
    reason="set SIM_PILOT_LIVE_OPENTTD_ANALYSIS=1 for read-only live analysis",
)
def test_live_openttd_deterministic_analysis_is_read_only() -> None:
    world = asyncio.run(capture_openttd_world_snapshot())
    service = AnalysisService(default_analyzer_registry())
    for analysis_type in (
        AnalysisType.COMPANY_HEALTH,
        AnalysisType.VEHICLE_PERFORMANCE,
        AnalysisType.SERVICE_COVERAGE,
    ):
        response = service.analyze(
            AnalysisRequest(
                analysis_type=analysis_type,
                question=f"Live read-only {analysis_type.value} check.",
            ),
            world,
        )
        assert response.snapshot_id == world.metadata.snapshot_id
        assert all(not item.executable for item in response.recommendations)


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("SIM_PILOT_LIVE_OPENTTD_ANALYSIS") != "1"
    or os.getenv("SIM_PILOT_LIVE_CODEX_ANALYSIS") != "1",
    reason="set both live analysis flags for the Codex explanation check",
)
def test_live_codex_explanation_cannot_change_deterministic_metrics() -> None:
    world = asyncio.run(capture_openttd_world_snapshot())
    request = AnalysisRequest(
        analysis_type=AnalysisType.COMPANY_HEALTH,
        question="Why am I losing money?",
    )
    compiler = ScriptedAnalysisCompiler((AnalysisCompilation(request=request),))
    query = AnalysisQueryService(AnalysisService(default_analyzer_registry()))
    _, response = asyncio.run(
        query.ask(
            request.question,
            world,
            compiler=compiler,
            explanation_provider=CodexExplanationProvider(
                model=codex_model(), timeout_seconds=codex_timeout_seconds()
            ),
        )
    )
    assert response is not None
    if response.explanation is not None:
        deterministic = {item.finding_id: item.metric_value for item in response.findings}
        for statement in response.explanation.statements:
            for metric in statement.metric_references:
                assert metric.metric_value == deterministic[metric.finding_id]
