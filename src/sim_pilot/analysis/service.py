"""Application service for deterministic analysis over supplied snapshots."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sim_pilot.analysis.analyzers import AnalyzerResult
from sim_pilot.analysis.catalog import validate_analysis_request
from sim_pilot.analysis.compatibility import validate_comparison
from sim_pilot.analysis.contracts import (
    AnalysisRequest,
    AnalysisResponse,
    AnalysisSnapshotMetadata,
    AnalysisStatus,
    SnapshotSource,
)
from sim_pilot.analysis.errors import AnalysisComparisonError, AnalyzerResultError
from sim_pilot.analysis.interaction import compose_interaction
from sim_pilot.analysis.registry import AnalyzerRegistry
from sim_pilot.domain.world import CoverageStatus, WorldSnapshot


class AnalysisService:
    def __init__(
        self,
        registry: AnalyzerRegistry,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._registry = registry
        self._clock = clock

    def analyze(
        self,
        request: AnalysisRequest,
        snapshot: WorldSnapshot,
        comparison: WorldSnapshot | None = None,
    ) -> AnalysisResponse:
        capability = validate_analysis_request(request)
        comparison_limitations: tuple[str, ...] = ()
        if request.comparison_snapshot_id is not None:
            if comparison is None:
                raise AnalysisComparisonError("the requested comparison snapshot was not supplied")
            comparison_limitations = validate_comparison(
                snapshot,
                comparison,
                expected_snapshot_id=request.comparison_snapshot_id,
            ).limitations
        elif comparison is not None:
            raise AnalysisComparisonError("comparison input requires an explicit snapshot ID")

        quality_limitations = _quality_limitations(snapshot, capability.required_coverage)
        analyzer = self._registry.get(request.analysis_type)
        result = analyzer.analyze(request, snapshot, comparison)
        _validate_result(request, snapshot, comparison, result)
        findings = result.findings[: request.maximum_findings]
        retained_ids = {item.finding_id for item in findings}
        recommendations = (
            tuple(
                item
                for item in result.recommendations
                if set(item.supporting_finding_ids).issubset(retained_ids)
            )
            if request.include_recommendations
            else ()
        )
        retained_recommendations = {item.recommendation_id for item in recommendations}
        findings = tuple(
            item.model_copy(
                update={
                    "recommendation_ids": tuple(
                        identifier
                        for identifier in item.recommendation_ids
                        if identifier in retained_recommendations
                    )
                }
            )
            for item in findings
        )
        limitations = tuple(
            dict.fromkeys((*result.limitations, *quality_limitations, *comparison_limitations))
        )
        status = result.status
        if limitations and status is AnalysisStatus.COMPLETED:
            status = AnalysisStatus.COMPLETED_WITH_LIMITATIONS
        status, answer, presentation = compose_interaction(
            request,
            snapshot=snapshot,
            comparison=comparison,
            status=status,
            findings=findings,
            recommendations=recommendations,
            limitations=limitations,
            fallback_answer=result.answer,
            population=result.population,
        )
        generated_at = self._clock()
        metadata = snapshot.metadata
        return AnalysisResponse(
            request=request,
            snapshot_id=snapshot.metadata.snapshot_id,
            snapshot_metadata=AnalysisSnapshotMetadata(
                source=SnapshotSource.SUPPLIED_SNAPSHOT,
                snapshot_age_seconds=max(
                    0.0, (generated_at - metadata.captured_at).total_seconds()
                ),
                collection_interval_game_days=(
                    metadata.capture_completed_game_date - metadata.capture_started_game_date
                ),
                world_id=metadata.world_id,
                observer_company_id=metadata.observer_company_id,
                save_generation=metadata.save_generation,
                capability_fingerprint=metadata.capability_fingerprint,
                snapshot_bridge_sequence=metadata.bridge_sequence,
                bridge_synchronization_state="snapshot_metadata_only",
                openttd_version=metadata.game_version,
            ),
            status=status,
            answer=answer,
            findings=findings,
            recommendations=recommendations,
            assumptions=result.assumptions,
            limitations=limitations,
            unsupported_parts=result.unsupported_parts,
            presentation=presentation,
            population=result.population,
            generated_at=generated_at,
        )


def _quality_limitations(snapshot: WorldSnapshot, required: frozenset[str]) -> tuple[str, ...]:
    limitations: list[str] = []
    if not snapshot.metadata.complete:
        limitations.append("The world snapshot is incomplete.")
    coverage = {item.category: item.status for item in snapshot.coverage}
    for category in sorted(required):
        status = coverage.get(category)
        if status is CoverageStatus.PARTIAL:
            limitations.append(f"{category} coverage is partial.")
        elif status is CoverageStatus.UNAVAILABLE or status is None:
            limitations.append(f"{category} coverage is unavailable.")
    return tuple(limitations)


def _validate_result(
    request: AnalysisRequest,
    snapshot: WorldSnapshot,
    comparison: WorldSnapshot | None,
    result: AnalyzerResult,
) -> None:
    finding_ids = [item.finding_id for item in result.findings]
    recommendation_ids = [item.recommendation_id for item in result.recommendations]
    if len(set(finding_ids)) != len(finding_ids):
        raise AnalyzerResultError("analyzer returned duplicate finding IDs")
    if len(set(recommendation_ids)) != len(recommendation_ids):
        raise AnalyzerResultError("analyzer returned duplicate recommendation IDs")
    findings = set(finding_ids)
    recommendations = {item.recommendation_id: item for item in result.recommendations}
    allowed_snapshots = {snapshot.metadata.snapshot_id}
    if comparison is not None:
        allowed_snapshots.add(comparison.metadata.snapshot_id)
    for finding in result.findings:
        if finding.analysis_type is not request.analysis_type:
            raise AnalyzerResultError("finding analysis type does not match the request")
        if not set(finding.recommendation_ids).issubset(recommendations):
            raise AnalyzerResultError("finding references an unknown recommendation")
        for evidence in finding.evidence:
            if evidence.snapshot_id not in allowed_snapshots:
                raise AnalyzerResultError("evidence references an unknown snapshot")
            if (
                evidence.comparison_snapshot_id is not None
                and evidence.comparison_snapshot_id not in allowed_snapshots
            ):
                raise AnalyzerResultError("evidence references an unknown comparison snapshot")
    for recommendation in result.recommendations:
        if not set(recommendation.supporting_finding_ids).issubset(findings):
            raise AnalyzerResultError("recommendation references an unknown finding")
