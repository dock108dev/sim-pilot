"""Read-only orchestration for compile, deterministic analysis, and optional explanation."""

from __future__ import annotations

from sim_pilot.analysis.compiler import AnalysisCompilation, AnalysisCompiler
from sim_pilot.analysis.contracts import AnalysisRequest, AnalysisResponse
from sim_pilot.analysis.explanation import (
    ExplanationProvider,
    ExplanationStyle,
    explanation_input,
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
        compilation = await compiler.compile(question)
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
        return compilation, response.model_copy(update={"explanation": explanation})

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
            return response.model_copy(
                update={"explanation": validate_explanation(explanation, response)}
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
