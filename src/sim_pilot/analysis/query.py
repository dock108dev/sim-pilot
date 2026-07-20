"""Read-only orchestration for compile, deterministic analysis, and optional explanation."""

from __future__ import annotations

from sim_pilot.analysis.compiler import (
    AnalysisCompilation,
    AnalysisCompiler,
    AnalysisCompilerContext,
)
from sim_pilot.analysis.contracts import AnalysisRequest, AnalysisResponse
from sim_pilot.analysis.explanation import (
    ExplanationProvider,
    ExplanationStyle,
    explanation_input,
    retain_valuable_explanation,
    validate_explanation,
)
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.domain.world import WorldSnapshot


class AnalysisQueryService:
    def __init__(self, analysis_service: AnalysisService) -> None:
        self._analysis_service = analysis_service

    async def ask(
        self,
        question: str,
        snapshot: WorldSnapshot,
        *,
        compiler: AnalysisCompiler,
        comparison: WorldSnapshot | None = None,
        explanation_provider: ExplanationProvider | None = None,
        style: ExplanationStyle = ExplanationStyle.COMPACT,
    ) -> tuple[AnalysisCompilation, AnalysisResponse | None]:
        compilation = await compiler.compile(
            question,
            context=AnalysisCompilerContext(
                comparison_snapshot_id=(
                    None if comparison is None else comparison.metadata.snapshot_id
                )
            ),
        )
        if compilation.request is None:
            return compilation, None
        response = self._analysis_service.analyze(compilation.request, snapshot, comparison)
        if explanation_provider is None:
            return compilation, response
        try:
            explanation = await explanation_provider.explain(
                explanation_input(response, style=style)
            )
            explanation = validate_explanation(explanation, response)
        except Exception as error:
            fallback = response.model_copy(
                update={
                    "limitations": tuple(
                        dict.fromkeys(
                            (
                                *response.limitations,
                                "Model explanation was rejected; deterministic output retained: "
                                f"{error}",
                            )
                        )
                    )
                }
            )
            return compilation, fallback
        return compilation, response.model_copy(
            update={"explanation": retain_valuable_explanation(explanation, response)}
        )

    async def analyze_request(
        self,
        request: AnalysisRequest,
        snapshot: WorldSnapshot,
        *,
        comparison: WorldSnapshot | None = None,
        explanation_provider: ExplanationProvider | None = None,
        style: ExplanationStyle = ExplanationStyle.COMPACT,
    ) -> AnalysisResponse:
        response = self._analysis_service.analyze(request, snapshot, comparison)
        if explanation_provider is None:
            return response
        try:
            explanation = await explanation_provider.explain(
                explanation_input(response, style=style)
            )
            validated = validate_explanation(explanation, response)
            return response.model_copy(
                update={"explanation": retain_valuable_explanation(validated, response)}
            )
        except Exception as error:
            return response.model_copy(
                update={
                    "limitations": tuple(
                        dict.fromkeys(
                            (
                                *response.limitations,
                                "Model explanation was rejected; deterministic output retained: "
                                f"{error}",
                            )
                        )
                    )
                }
            )
