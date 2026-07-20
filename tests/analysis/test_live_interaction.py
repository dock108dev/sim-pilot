"""Explicitly gated Phase 9 read-only live interaction regression."""

import asyncio
import os
from pathlib import Path

import pytest

from sim_pilot.analysis.compiler import AnalysisCompilerContext, DeterministicAnalysisCompiler
from sim_pilot.analysis.contracts import (
    AnalysisResponse,
    AnalysisStatus,
    AnalysisSubjectType,
    InspectionGuidanceStatus,
)
from sim_pilot.analysis.output import render_analysis
from sim_pilot.analysis.query import AnalysisQueryService
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.analysis.session import AnalysisSessionStore
from sim_pilot.analysis_provider import CodexAnalysisCompiler, CodexExplanationProvider
from sim_pilot.cli import capture_openttd_world_snapshot
from sim_pilot.config import codex_model, codex_timeout_seconds
from sim_pilot.domain.world import WorldSnapshot
from sim_pilot.openttd.config import openttd_configuration
from sim_pilot.openttd.world_diff import diff_world

EXPECTED_WORLD_ID = "spb-1636440848-1049736244"
MINIMUM_SAVE_GENERATION = 334
EXPECTED_COMPANY_NAME = "Sim Pilot Founder Test"


def _assert_read_only() -> None:
    config = openttd_configuration()
    assert not config.allow_writes
    assert not config.allow_gamescript_writes


def _assert_expected_save(world: WorldSnapshot) -> None:
    assert world.metadata.world_id == EXPECTED_WORLD_ID
    assert world.metadata.save_generation >= MINIMUM_SAVE_GENERATION
    company = next(
        item for item in world.companies if item.id == world.metadata.observer_company_id
    )
    assert company.name == EXPECTED_COMPANY_NAME


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("SIM_PILOT_LIVE_OPENTTD_INTERACTION") != "1",
    reason="set SIM_PILOT_LIVE_OPENTTD_INTERACTION=1 for Phase 9 read-only regression",
)
def test_live_phase9_question_set_is_question_sensitive_and_read_only(
    tmp_path: Path,
) -> None:
    _assert_read_only()
    previous = asyncio.run(capture_openttd_world_snapshot())
    observed = asyncio.run(capture_openttd_world_snapshot())
    _assert_expected_save(previous)
    _assert_expected_save(observed)
    current = diff_world(previous, observed)
    compiler = DeterministicAnalysisCompiler()
    service = AnalysisService(default_analyzer_registry())

    questions = (
        "Why am I losing money?",
        "How much debt do I have?",
        "Which vehicles lost the most money last year?",
        "Which station should I inspect first?",
        "Which routes have the most losing vehicles?",
        "Which industry is the best observed opportunity?",
    )
    responses: list[AnalysisResponse] = []
    for question in questions:
        compilation = asyncio.run(compiler.compile(question))
        assert compilation.request is not None
        response = service.analyze(compilation.request, current)
        assert response.answer
        assert all(not item.executable for item in response.recommendations)
        _assert_inspection_guidance(response, current)
        responses.append(response)

    missing = asyncio.run(compiler.compile("What changed?"))
    assert missing.request is not None
    missing_response = service.analyze(missing.request, current)
    assert missing_response.status is AnalysisStatus.INSUFFICIENT_DATA
    assert not missing_response.answer.startswith("Observed 0")
    _assert_inspection_guidance(missing_response, current)

    compared = asyncio.run(
        compiler.compile(
            "What changed since the last snapshot?",
            context=AnalysisCompilerContext(comparison_snapshot_id=previous.metadata.snapshot_id),
        )
    )
    assert compared.request is not None
    compared_response = service.analyze(compared.request, current, previous)
    assert compared_response.status in {
        AnalysisStatus.COMPLETED,
        AnalysisStatus.COMPLETED_WITH_LIMITATIONS,
        AnalysisStatus.INSUFFICIENT_DATA,
    }
    assert not compared_response.answer.startswith("Observed 0")
    _assert_inspection_guidance(compared_response, current)

    vehicle_response = responses[2]
    store = AnalysisSessionStore(tmp_path / "sessions")
    store.save(vehicle_response, current)
    follow_up = asyncio.run(
        compiler.compile(
            "Why did you flag that vehicle?",
            context=store.compiler_context(current),
        )
    )
    assert follow_up.request is not None
    assert follow_up.request.subject_type is AnalysisSubjectType.VEHICLE
    follow_up_response = service.analyze(follow_up.request, current)
    assert follow_up_response.answer
    _assert_inspection_guidance(follow_up_response, current)


def _assert_inspection_guidance(response: AnalysisResponse, world: WorldSnapshot) -> None:
    assert response.presentation is not None
    guidance = response.presentation.inspection_guidance
    rendered = render_analysis(response, snapshot=world)
    assert "\nInspect next\n" in rendered
    if guidance.status is InspectionGuidanceStatus.RECOMMENDED:
        assert guidance.target_label is not None
        assert guidance.target_label in rendered
        assert guidance.supporting_finding_ids == (response.presentation.decisive_finding_id,)
    else:
        assert guidance.unavailable_reason
        assert "No responsible next inspection can be recommended" in rendered


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("SIM_PILOT_LIVE_OPENTTD_INTERACTION") != "1"
    or os.getenv("SIM_PILOT_LIVE_CODEX_INTERACTION") != "1",
    reason="set both Phase 9 live flags for at most two Codex invocations",
)
def test_live_phase9_codex_compilation_remains_bounded() -> None:
    _assert_read_only()
    world = asyncio.run(capture_openttd_world_snapshot())
    _assert_expected_save(world)
    query = AnalysisQueryService(AnalysisService(default_analyzer_registry()))
    compilation, response = asyncio.run(
        query.ask(
            "Why am I losing money?",
            world,
            compiler=CodexAnalysisCompiler(
                model=codex_model(), timeout_seconds=codex_timeout_seconds()
            ),
        )
    )
    assert compilation.request is not None
    assert response is not None
    assert response.answer
    assert all(not item.executable for item in response.recommendations)


@pytest.mark.live
@pytest.mark.skipif(
    os.getenv("SIM_PILOT_LIVE_OPENTTD_INTERACTION") != "1"
    or os.getenv("SIM_PILOT_LIVE_CODEX_INTERACTION") != "1",
    reason="set both Phase 9 live flags for one value-gated explanation invocation",
)
def test_live_phase9_codex_explanation_is_value_gated_and_faithful() -> None:
    _assert_read_only()
    world = asyncio.run(capture_openttd_world_snapshot())
    _assert_expected_save(world)
    compilation = asyncio.run(DeterministicAnalysisCompiler().compile("Why am I losing money?"))
    assert compilation.request is not None
    response = asyncio.run(
        AnalysisQueryService(AnalysisService(default_analyzer_registry())).analyze_request(
            compilation.request,
            world,
            explanation_provider=CodexExplanationProvider(
                model=codex_model(), timeout_seconds=codex_timeout_seconds()
            ),
        )
    )
    assert response.answer
    assert response.explanation_value.value in {
        "improved_answer",
        "neutral",
        "rejected_by_validator",
        "provider_failed",
    }
    if response.explanation is not None:
        authoritative = {
            item.finding_id: (item.metric_name, item.metric_value) for item in response.findings
        }
        for statement in response.explanation.statements:
            for metric in statement.metric_references:
                assert (metric.metric_name, metric.metric_value) == authoritative[metric.finding_id]
