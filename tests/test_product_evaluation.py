"""Offline contract tests for the bounded product evaluation exercise."""

import asyncio
import json
import stat
from collections import Counter
from pathlib import Path

from typer.testing import CliRunner

from sim_pilot.cli import INVALID_INPUT, app
from sim_pilot.domain import (
    Action,
    AuthorityPolicy,
    Decision,
    DecisionType,
    Objective,
    ObjectiveType,
    TaskSpecification,
)
from sim_pilot.intent_compiler import CompilerResponse
from sim_pilot.intent_compiler.models import CompilerProviderResult
from sim_pilot.product_evaluation import (
    EvaluationRunConfiguration,
    load_evaluation_cases,
    run_product_evaluation,
)
from sim_pilot.provider_metadata import ProviderMetadata, ProviderTokenUsage
from sim_pilot.runtime.decision_context import DecisionContext, DecisionProviderResult

FIXTURE = Path("tests/fixtures/product_evaluation_instructions.json")


class SuccessfulCompiler:
    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def compile(self, instruction: str) -> CompilerProviderResult:
        self.calls.append(instruction)
        return CompilerProviderResult(
            response=CompilerResponse(
                specification=TaskSpecification(
                    objective=Objective(
                        type=ObjectiveType.REACH_RESOURCE,
                        description="Reach the cash target.",
                        parameters={"resource": "cash", "target": 1_000_000},
                    ),
                    authority=AuthorityPolicy(),
                ),
                assumptions=(),
                warnings=(),
                unsupported_requests=(),
                ambiguities=(),
            ),
            metadata=ProviderMetadata(
                provider="offline-test",
                model="fixture-model",
                token_usage=ProviderTokenUsage(
                    input_tokens=100,
                    output_tokens=20,
                    total_tokens=120,
                ),
            ),
        )


class FailingCompiler:
    async def compile(self, instruction: str) -> CompilerProviderResult:
        del instruction
        raise RuntimeError("synthetic provider failure")


class AdvanceDecisionProvider:
    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        del context
        return DecisionProviderResult(
            decision=Decision(
                type=DecisionType.EXECUTE,
                reason="Advance one deterministic tick.",
                action=Action(
                    type="advance_time",
                    parameters={"ticks": 1},
                    expected_effect="Advance one tick.",
                ),
            ),
            metadata=ProviderMetadata(
                provider="offline-test",
                model="fixture-model",
                token_usage=ProviderTokenUsage(
                    input_tokens=50,
                    output_tokens=10,
                    total_tokens=60,
                ),
            ),
        )


def configuration() -> EvaluationRunConfiguration:
    return EvaluationRunConfiguration(
        compiler_provider="openai",
        decision_provider="openai",
        compiler_model="fixture-model",
        decision_model="fixture-model",
        input_cost_per_million_usd=2.0,
        output_cost_per_million_usd=8.0,
        max_runtime_iterations=2,
        max_output_tokens_per_call=2048,
    )


def test_product_fixture_covers_required_player_instruction_categories() -> None:
    cases = load_evaluation_cases(FIXTURE)
    categories = Counter(case.category for case in cases)

    assert len(cases) >= 30
    assert set(categories) == {
        "clear_supported",
        "informal_supported",
        "ambiguous",
        "contradictory",
        "unsupported",
        "openttd_specific",
    }
    assert all(count >= 4 for count in categories.values())
    assert all(case.adapter == "reference" for case in cases if case.run_runtime)
    assert any(case.adapter == "openttd" for case in cases)


def test_evaluation_is_resumable_private_and_preserves_manual_review(tmp_path: Path) -> None:
    compiler_calls: list[str] = []
    output = tmp_path / "private-results"
    selected = frozenset({"informal-001"})

    first = asyncio.run(
        run_product_evaluation(
            fixture_path=FIXTURE,
            output_directory=output,
            compiler_provider_factory=lambda case: SuccessfulCompiler(compiler_calls),
            decision_provider_factory=lambda case: AdvanceDecisionProvider(),
            configuration=configuration(),
            case_ids=selected,
        )
    )

    assert first["case_count"] == 1
    assert first["provider_call_count"] == 1
    assert len(compiler_calls) == 1
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE((output / "results" / "informal-001.json").stat().st_mode) == 0o600
    manifest = json.loads((output / "manifest.json").read_text())
    assert "api_key" not in json.dumps(manifest).lower()
    assert manifest["maximum_provider_calls"] == 1

    review_path = output / "manual_review.json"
    review = json.loads(review_path.read_text())
    review[0]["manual_rating"] = "correct"
    review[0]["reviewer_notes"] = "Clear and faithful."
    review_path.write_text(json.dumps(review))

    second = asyncio.run(
        run_product_evaluation(
            fixture_path=FIXTURE,
            output_directory=output,
            compiler_provider_factory=lambda case: SuccessfulCompiler(compiler_calls),
            decision_provider_factory=lambda case: AdvanceDecisionProvider(),
            configuration=configuration(),
            case_ids=selected,
        )
    )

    assert second == first
    assert len(compiler_calls) == 1
    preserved = json.loads(review_path.read_text())
    assert preserved[0]["manual_rating"] == "correct"
    assert preserved[0]["reviewer_notes"] == "Clear and faithful."


def test_paid_case_failure_is_retained_as_evaluation_evidence(tmp_path: Path) -> None:
    output = tmp_path / "failed-results"

    aggregate = asyncio.run(
        run_product_evaluation(
            fixture_path=FIXTURE,
            output_directory=output,
            compiler_provider_factory=lambda case: FailingCompiler(),
            decision_provider_factory=lambda case: AdvanceDecisionProvider(),
            configuration=configuration(),
            case_ids=frozenset({"unsupported-001"}),
        )
    )

    result = json.loads((output / "results" / "unsupported-001.json").read_text())
    assert result["failure_category"] == "RuntimeError"
    assert result["failure_message"] == "synthetic provider failure"
    assert result["compilation_status"] is None
    assert aggregate["failure_categories"] == {"RuntimeError": 1}


def test_cli_refuses_to_select_hosted_evaluation_providers_implicitly(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        app,
        ["evaluate", "product", "--record-dir", str(tmp_path / "must-not-exist")],
    )

    assert result.exit_code == INVALID_INPUT
    assert "--compiler-provider openai is required" in result.output
    assert not (tmp_path / "must-not-exist").exists()
