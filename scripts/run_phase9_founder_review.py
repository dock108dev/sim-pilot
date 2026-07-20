"""Generate the focused Phase 9 founder review from one approved live save."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sim_pilot.analysis.compiler import AnalysisCompilerContext, DeterministicAnalysisCompiler
from sim_pilot.analysis.contracts import AnalysisResponse
from sim_pilot.analysis.output import render_analysis
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.analysis.session import AnalysisSessionStore
from sim_pilot.cli import capture_openttd_world_snapshot
from sim_pilot.domain.world import WorldSnapshot
from sim_pilot.openttd.config import openttd_configuration
from sim_pilot.openttd.world_diff import diff_world
from sim_pilot.private_files import atomic_write_private_text


class ReviewCase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    case_id: str
    question: str
    comparison: bool = False
    context_seed: str | None = None


class ReviewItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    case_id: str
    question: str
    answer: str
    status: str
    analyzer: str | None
    subject: str | None
    metric: str | None
    period: str | None
    comparison_required: bool | None
    word_count: int
    explanation_value: str
    manual_rating: Literal["correct", "acceptable", "annoying", "incorrect", "unsafe"] | None = None
    revealed_nonobvious_information: Literal["yes", "partially", "no"] | None = None
    would_use_during_gameplay: Literal["yes", "maybe", "no"] | None = None
    answered_exact_question: Literal["yes", "partially", "no"] | None = None
    too_verbose: Literal["yes", "no"] | None = None
    recommendation_useful: Literal["yes", "partially", "no"] | None = None
    limitation_relevant: Literal["yes", "no"] | None = None
    reviewer_notes: str = ""


CASES = (
    ReviewCase(case_id="phase9-health-01", question="How healthy is my company?"),
    ReviewCase(case_id="phase9-loss-01", question="Why am I losing money?"),
    ReviewCase(case_id="phase9-loss-02", question="Is my company making or losing money?"),
    ReviewCase(case_id="phase9-debt-01", question="Am I carrying too much debt?"),
    ReviewCase(case_id="phase9-debt-02", question="How much debt do I have?"),
    ReviewCase(case_id="phase9-cash-01", question="How much cash is available?"),
    ReviewCase(
        case_id="phase9-company-change-01",
        question="Is the company improving?",
        comparison=True,
    ),
    ReviewCase(
        case_id="phase9-vehicle-best-01",
        question="Which trains performed best last year?",
    ),
    ReviewCase(
        case_id="phase9-vehicle-worst-01",
        question="Which vehicle lost the most money last year?",
    ),
    ReviewCase(
        case_id="phase9-fleet-type-01",
        question="Which vehicle type is dragging down the company?",
    ),
    ReviewCase(case_id="phase9-idle-01", question="Are any vehicles idle?"),
    ReviewCase(
        case_id="phase9-station-priority-01",
        question="Which station should I inspect first?",
    ),
    ReviewCase(
        case_id="phase9-station-waiting-01",
        question="Which station has the most waiting cargo?",
    ),
    ReviewCase(
        case_id="phase9-route-loss-count-01",
        question="Which routes have the most losing vehicles?",
    ),
    ReviewCase(case_id="phase9-route-worst-01", question="Which route is performing worst?"),
    ReviewCase(
        case_id="phase9-industry-01",
        question="Which industry looks like the best observed opportunity?",
    ),
    ReviewCase(
        case_id="phase9-cargo-01",
        question="Which cargo types are missing from my network?",
    ),
    ReviewCase(
        case_id="phase9-change-valid-01",
        question="What changed since the last snapshot?",
        comparison=True,
    ),
    ReviewCase(case_id="phase9-change-missing-01", question="What changed?"),
    ReviewCase(
        case_id="phase9-anomaly-01",
        question="Are there any unusual changes?",
        comparison=True,
    ),
    ReviewCase(
        case_id="phase9-forecast-01",
        question="Predict the most profitable route in ten years.",
    ),
    ReviewCase(
        case_id="phase9-followup-vehicle-01",
        question="Why did you flag that vehicle?",
        context_seed="Which vehicle lost the most money last year?",
    ),
    ReviewCase(
        case_id="phase9-followup-route-01",
        question="Why is this route losing money?",
        context_seed="Which route is performing worst?",
    ),
    ReviewCase(
        case_id="phase9-followup-station-01",
        question="What makes this station worth inspecting?",
        context_seed="Which station should I inspect first?",
    ),
)


async def _capture_pair() -> tuple[WorldSnapshot, WorldSnapshot]:
    previous = await capture_openttd_world_snapshot()
    observed = await capture_openttd_world_snapshot()
    return previous, diff_world(previous, observed)


def _analyze(
    question: str,
    *,
    context: AnalysisCompilerContext,
    current: WorldSnapshot,
    previous: WorldSnapshot,
    use_comparison: bool,
    compiler: DeterministicAnalysisCompiler,
    service: AnalysisService,
) -> tuple[AnalysisResponse | None, str, str]:
    compilation = asyncio.run(compiler.compile(question, context=context))
    if compilation.request is None:
        answer = compilation.clarification or compilation.unsupported_reason or "No answer."
        status = "clarification_required" if compilation.clarification else "unsupported"
        return None, answer, status
    request = compilation.request.model_copy(
        update={
            "comparison_snapshot_id": (previous.metadata.snapshot_id if use_comparison else None)
        }
    )
    response = service.analyze(
        request,
        current,
        previous if use_comparison else None,
    )
    return response, render_analysis(response, snapshot=current), response.status.value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config = openttd_configuration()
    if config.allow_writes or config.allow_gamescript_writes:
        raise RuntimeError("Phase 9 founder review requires both OpenTTD write flags disabled")

    previous, current = asyncio.run(_capture_pair())
    output = args.output or (
        Path("data/founder-intelligence")
        / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-phase9-review"
    )
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    atomic_write_private_text(
        output / "comparison-snapshot.json", previous.model_dump_json(indent=2)
    )
    atomic_write_private_text(output / "current-snapshot.json", current.model_dump_json(indent=2))

    compiler = DeterministicAnalysisCompiler()
    service = AnalysisService(default_analyzer_registry())
    store = AnalysisSessionStore(output / "sessions")
    items: list[ReviewItem] = []
    for case in CASES:
        comparison_id = previous.metadata.snapshot_id if case.comparison else None
        context = AnalysisCompilerContext(comparison_snapshot_id=comparison_id)
        if case.context_seed is not None:
            seed_response, _, _ = _analyze(
                case.context_seed,
                context=AnalysisCompilerContext(),
                current=current,
                previous=previous,
                use_comparison=False,
                compiler=compiler,
                service=service,
            )
            if seed_response is None:
                raise RuntimeError(f"context seed failed for {case.case_id}")
            store.save(seed_response, current)
            context = store.compiler_context(
                current,
                comparison_snapshot_id=comparison_id,
            )
        response, answer, status = _analyze(
            case.question,
            context=context,
            current=current,
            previous=previous,
            use_comparison=case.comparison,
            compiler=compiler,
            service=service,
        )
        request = None if response is None else response.request
        intent = None if request is None else request.answer_intent
        items.append(
            ReviewItem(
                case_id=case.case_id,
                question=case.question,
                answer=answer,
                status=status,
                analyzer=(None if request is None else request.analysis_type.value),
                subject=(
                    None
                    if request is None or request.subject_type is None
                    else request.subject_type.value
                ),
                metric=(
                    None
                    if intent is None or intent.requested_metric is None
                    else intent.requested_metric.value
                ),
                period=(None if intent is None or intent.period is None else intent.period.value),
                comparison_required=(None if intent is None else intent.comparison_required),
                word_count=len(answer.split()),
                explanation_value=(
                    "not_invoked" if response is None else response.explanation_value.value
                ),
            )
        )

    company = next(
        item for item in current.companies if item.id == current.metadata.observer_company_id
    )
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "case_count": len(items),
        "world_id": current.metadata.world_id,
        "company_id": company.id,
        "company_name": company.name,
        "comparison_snapshot_id": previous.metadata.snapshot_id,
        "current_snapshot_id": current.metadata.snapshot_id,
        "write_flags_enabled": False,
        "model_invocations": 0,
    }
    atomic_write_private_text(
        output / "manual-review.json",
        "[\n" + ",\n".join(item.model_dump_json(indent=2) for item in items) + "\n]",
    )
    atomic_write_private_text(output / "manifest.json", json.dumps(manifest, indent=2))
    print(output)


if __name__ == "__main__":
    main()
