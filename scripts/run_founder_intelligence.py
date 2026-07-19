"""Run the explicitly authorized Phase 8C live founder session."""

from __future__ import annotations

import asyncio
import os
from argparse import ArgumentParser
from pathlib import Path
from time import perf_counter

from sim_pilot.analysis.evaluation import load_founder_intelligence_cases
from sim_pilot.analysis.founder_session import run_founder_session
from sim_pilot.analysis_provider import CodexAnalysisCompiler, CodexExplanationProvider
from sim_pilot.cli import capture_openttd_world_snapshot
from sim_pilot.config import codex_executable, codex_model, codex_timeout_seconds
from sim_pilot.domain.world import WorldSnapshot
from sim_pilot.private_files import atomic_write_private_text

EXPLANATION_CASES = frozenset(
    {
        "company-health-001",
        "vehicles-001",
        "stations-002",
        "routes-001",
        "changes-001",
    }
)


def main() -> None:
    parser = ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/founder_intelligence_questions.json"),
    )
    parser.add_argument("--current-snapshot", type=Path)
    parser.add_argument("--comparison-snapshot", type=Path)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--explanation-case-id", action="append", default=[])
    arguments = parser.parse_args()
    _require_safe_live_gates()

    if (arguments.current_snapshot is None) != (arguments.comparison_snapshot is None):
        raise RuntimeError("current and comparison snapshot files must be supplied together")
    if arguments.current_snapshot is None:
        capture_started = perf_counter()
        comparison = asyncio.run(capture_openttd_world_snapshot())
        comparison_ms = (perf_counter() - capture_started) * 1_000
        capture_started = perf_counter()
        current = asyncio.run(capture_openttd_world_snapshot())
        current_ms = (perf_counter() - capture_started) * 1_000
    else:
        assert arguments.comparison_snapshot is not None
        current = WorldSnapshot.model_validate_json(
            arguments.current_snapshot.read_text(encoding="utf-8"), strict=True
        )
        comparison = WorldSnapshot.model_validate_json(
            arguments.comparison_snapshot.read_text(encoding="utf-8"), strict=True
        )
        current_ms = 0.0
        comparison_ms = 0.0

    compiler = CodexAnalysisCompiler(
        model=codex_model(),
        timeout_seconds=codex_timeout_seconds(),
        executable=codex_executable(),
    )
    explainer = CodexExplanationProvider(
        model=codex_model(),
        timeout_seconds=codex_timeout_seconds(),
        executable=codex_executable(),
    )
    cases = load_founder_intelligence_cases(arguments.fixture)
    selected_case_ids = frozenset(arguments.case_id)
    if selected_case_ids:
        cases = tuple(case for case in cases if case.case_id in selected_case_ids)
        missing = selected_case_ids - {case.case_id for case in cases}
        if missing:
            raise RuntimeError(f"unknown founder case IDs: {', '.join(sorted(missing))}")
    explanation_case_ids = (
        frozenset(arguments.explanation_case_id)
        if arguments.explanation_case_id
        else EXPLANATION_CASES
    )
    manifest = run_founder_session(
        cases=cases,
        current=current,
        comparison=comparison,
        compiler=compiler,
        explanation_provider=explainer,
        compiler_metadata=lambda: compiler.last_metadata,
        explanation_metadata=lambda: explainer.last_metadata,
        output_directory=arguments.output,
        explanation_case_ids=explanation_case_ids,
    )
    atomic_write_private_text(
        arguments.output / "snapshot-latency.json",
        (
            "{\n"
            f'  "comparison_snapshot_ms": {comparison_ms:.3f},\n'
            f'  "current_snapshot_ms": {current_ms:.3f}\n'
            "}\n"
        ),
    )
    print(manifest.model_dump_json(indent=2))


def _require_safe_live_gates() -> None:
    required = (
        "SIM_PILOT_LIVE_OPENTTD_INTELLIGENCE",
        "SIM_PILOT_LIVE_CODEX_INTELLIGENCE",
    )
    if any(os.getenv(name) != "1" for name in required):
        raise RuntimeError("both Phase 8C live intelligence gates must equal 1")
    write_flags = (
        "SIM_PILOT_OPENTTD_ALLOW_WRITES",
        "SIM_PILOT_OPENTTD_GS_ALLOW_WRITES",
    )
    if any(os.getenv(name, "0") != "0" for name in write_flags):
        raise RuntimeError("all OpenTTD write flags must equal 0")


if __name__ == "__main__":
    main()
