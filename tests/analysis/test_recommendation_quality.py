import asyncio
import json
import re
from pathlib import Path
from typing import Literal

import pytest
from pydantic import BaseModel, ConfigDict, ValidationError

from sim_pilot.analysis.compiler import DeterministicAnalysisCompiler
from sim_pilot.analysis.contracts import InspectionGuidanceStatus
from sim_pilot.analysis.output import render_analysis
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.domain.world import (
    CargoFlow,
    CargoFlowScope,
    Company,
    Coordinates,
    Industry,
    Route,
    Station,
    Vehicle,
)
from tests.analysis.helpers import snapshot


class RecommendationQualityCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    case_id: str
    question: str
    world: Literal["full", "healthy", "empty-fleet"]
    expected_target: str | None
    expected_observation: str
    expected_answer_prefix: str | None = None
    expect_recommendation: bool


_CATALOG_PATH = Path(__file__).parents[1] / "fixtures" / "phase9_1_recommendation_quality.json"
_CASES = tuple(
    RecommendationQualityCase.model_validate(item, strict=True)
    for item in json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
)


def _vehicle(
    identifier: str,
    name: str,
    *,
    vehicle_type: str,
    profit: int,
    route_id: str | None,
    state: str = "running",
    in_depot: bool = False,
) -> Vehicle:
    return Vehicle(
        id=identifier,
        type=vehicle_type,
        name=name,
        age_days=1_000,
        profit_this_year=profit,
        profit_last_year=profit,
        running_state=state,
        coordinates=None,
        route_id=route_id,
        in_depot=in_depot,
        owner_id="company-1",
    )


def _world(kind: str):
    company = Company(
        id="company-1",
        name="Founder Transport",
        cash=2_000_000,
        loan=0,
        company_value=4_000_000,
        income=1_000_000,
        expenses=-250_000 if kind == "healthy" else -1_250_000,
    )
    if kind in {"healthy", "empty-fleet"}:
        return snapshot(company=company)

    vehicles = (
        _vehicle(
            "train-14",
            "Train 14",
            vehicle_type="rail",
            profit=-42_310,
            route_id="route-coal",
        ),
        _vehicle(
            "train-15",
            "Train 15",
            vehicle_type="rail",
            profit=-10_000,
            route_id="route-coal",
        ),
        _vehicle(
            "bus-2",
            "Bus 2",
            vehicle_type="road",
            profit=-100,
            route_id=None,
            state="stopped",
            in_depot=True,
        ),
    )
    exchange = Station(
        id="station-exchange",
        name="Buntborough Exchange",
        owner_id="company-1",
        coordinates=Coordinates(x=10, y=10),
        waiting_cargo=(
            CargoFlow(
                cargo_id="coal",
                cargo_type="Coal",
                scope=CargoFlowScope.STATION,
                entity_id="station-exchange",
                waiting=2_000,
            ),
        ),
        vehicle_count=1,
    )
    woods = Station(
        id="station-woods",
        name="Trunton Woods",
        owner_id="company-1",
        coordinates=Coordinates(x=30, y=10),
        vehicle_count=2,
    )
    route = Route(
        id="route-coal",
        owner_id="company-1",
        vehicle_ids=("train-14", "train-15"),
        ordered_station_ids=("station-exchange", "station-woods"),
        inferred_route_type="rail",
    )
    industry = Industry(
        id="industry-coal",
        type="coal_mine",
        name="Buntborough Coal Mine",
        coordinates=Coordinates(x=42, y=12),
        production=(
            CargoFlow(
                cargo_id="coal",
                cargo_type="Coal",
                scope=CargoFlowScope.INDUSTRY,
                entity_id="industry-coal",
                produced=900,
            ),
        ),
        produced_cargo_ids=("coal",),
    )
    return snapshot(company=company, vehicles=vehicles).model_copy(
        update={"stations": (exchange, woods), "routes": (route,), "industries": (industry,)}
    )


@pytest.mark.parametrize("case", _CASES, ids=lambda case: case.case_id)
def test_phase9_1_recommendation_quality_catalog(case: RecommendationQualityCase) -> None:
    compilation = asyncio.run(DeterministicAnalysisCompiler().compile(case.question))
    assert compilation.request is not None
    world = _world(case.world)
    response = AnalysisService(default_analyzer_registry()).analyze(compilation.request, world)
    assert response.presentation is not None
    guidance = response.presentation.inspection_guidance
    rendered = render_analysis(response, snapshot=world)
    inspect_next = rendered.split("\nInspect next\n", 1)[1].split("\n\n", 1)[0]

    if case.expect_recommendation:
        assert guidance.status is InspectionGuidanceStatus.RECOMMENDED
        assert case.expected_target is not None
        assert case.expected_target in inspect_next
        assert guidance.target_label is not None
        assert guidance.target_label in inspect_next
        assert guidance.supporting_finding_ids == (response.presentation.decisive_finding_id,)
    else:
        assert guidance.status is InspectionGuidanceStatus.NOT_RESPONSIBLE
        assert inspect_next.startswith("No responsible next inspection can be recommended")

    assert case.expected_observation in inspect_next
    if case.expected_answer_prefix is not None:
        assert response.answer.startswith(case.expected_answer_prefix)

    finding = next(
        (
            item
            for item in response.findings
            if item.finding_id == response.presentation.decisive_finding_id
        ),
        None,
    )
    if finding is not None:
        assert inspect_next.casefold() not in {
            finding.summary.casefold(),
            response.answer.casefold(),
        }
    assert not re.fullmatch(
        r"(?i)(inspect|review|investigate)( further| this| it)?\.?", inspect_next
    )
    assert not re.search(r"(?i)\b(proves?|is caused by|is due to|guarantees?)\b", inspect_next)
    assert len(inspect_next.split()) <= 34
    assert len(rendered.split()) <= 80


def test_route_loss_count_compact_evidence_omits_internal_route_identity() -> None:
    compilation = asyncio.run(
        DeterministicAnalysisCompiler().compile("Which routes have the most losing vehicles?")
    )
    assert compilation.request is not None
    world = _world("full")
    response = AnalysisService(default_analyzer_registry()).analyze(compilation.request, world)
    rendered = render_analysis(response, snapshot=world)

    assert "route-coal" not in rendered
    assert "2 of 2 vehicles lost money last year" in rendered
    assert len(rendered.split()) <= 80


def test_industry_opportunity_compact_evidence_does_not_repeat_the_name() -> None:
    compilation = asyncio.run(
        DeterministicAnalysisCompiler().compile(
            "Which industry looks like the best observed opportunity?"
        )
    )
    assert compilation.request is not None
    world = _world("full")
    response = AnalysisService(default_analyzer_registry()).analyze(compilation.request, world)
    rendered = render_analysis(response, snapshot=world)
    evidence = rendered.split("\nEvidence\n", 1)[1].split("\n\n", 1)[0]

    assert evidence.count("Buntborough Coal Mine") == 1
    assert "observed production is 900" in evidence
    assert len(rendered.split()) <= 80


def test_recommendation_quality_catalog_covers_required_phase9_1_surfaces() -> None:
    assert {case.case_id for case in _CASES} == {
        "losing-vehicle",
        "weak-vehicle-type",
        "worst-route",
        "high-waiting-station",
        "idle-vehicle",
        "industry-opportunity",
        "missing-cargo-coverage",
        "healthy-company",
        "insufficient-evidence",
        "false-premise-correction",
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("observation", "investigate further", "requires a concrete observation"),
        (
            "observation",
            "check the orders because the loss is due to low demand",
            "unsupported causal certainty",
        ),
        (
            "observation",
            "compare one two three four five six seven eight nine ten eleven twelve thirteen "
            "fourteen fifteen sixteen seventeen eighteen nineteen",
            "compact interaction budget",
        ),
        ("target_entity_id", "bus-2", "wrong entity"),
    ),
)
def test_guidance_contract_rejects_generic_causal_overlong_or_wrong_entity(
    field: str, value: str, message: str
) -> None:
    compilation = asyncio.run(
        DeterministicAnalysisCompiler().compile("Which vehicle lost the most money last year?")
    )
    assert compilation.request is not None
    world = _world("full")
    response = AnalysisService(default_analyzer_registry()).analyze(compilation.request, world)
    payload = response.model_dump()
    payload["presentation"]["inspection_guidance"][field] = value

    with pytest.raises(ValidationError, match=message):
        type(response).model_validate(payload, strict=True)


def test_guidance_contract_rejects_a_repeated_finding() -> None:
    compilation = asyncio.run(
        DeterministicAnalysisCompiler().compile("Which vehicle lost the most money last year?")
    )
    assert compilation.request is not None
    world = _world("full")
    response = AnalysisService(default_analyzer_registry()).analyze(compilation.request, world)
    assert response.presentation is not None
    finding = next(
        item
        for item in response.findings
        if item.finding_id == response.presentation.decisive_finding_id
    )
    payload = response.model_dump()
    payload["presentation"]["inspection_guidance"]["observation"] = finding.summary

    with pytest.raises(ValidationError, match="repeats the finding"):
        type(response).model_validate(payload, strict=True)
