"""Fail-closed compatibility checks for deterministic snapshot comparison."""

from __future__ import annotations

from dataclasses import dataclass

from sim_pilot.analysis.errors import AnalysisComparisonError
from sim_pilot.domain.world import WorldSnapshot


@dataclass(frozen=True)
class ComparisonCompatibility:
    limitations: tuple[str, ...] = ()


def validate_comparison(
    current: WorldSnapshot,
    comparison: WorldSnapshot,
    *,
    expected_snapshot_id: str | None,
) -> ComparisonCompatibility:
    if expected_snapshot_id is None:
        raise AnalysisComparisonError("a comparison snapshot was supplied without an explicit ID")
    if comparison.metadata.snapshot_id != expected_snapshot_id:
        raise AnalysisComparisonError("comparison snapshot does not match the requested ID")
    if current.metadata.snapshot_id == comparison.metadata.snapshot_id:
        raise AnalysisComparisonError("current and comparison snapshots must be different")
    if current.metadata.world_id != comparison.metadata.world_id:
        raise AnalysisComparisonError("cannot compare snapshots from different worlds")
    if current.metadata.game != comparison.metadata.game:
        raise AnalysisComparisonError("cannot compare snapshots from different games")
    if current.metadata.game_version != comparison.metadata.game_version:
        raise AnalysisComparisonError("cannot compare snapshots from different game versions")
    if current.metadata.capability_fingerprint != comparison.metadata.capability_fingerprint:
        raise AnalysisComparisonError("cannot compare snapshots with different capabilities")
    if not current.metadata.complete or not comparison.metadata.complete:
        raise AnalysisComparisonError("comparison requires two complete snapshots")
    if current.metadata.game_date < comparison.metadata.game_date:
        raise AnalysisComparisonError("comparison snapshot must not be newer than current snapshot")
    if (
        current.metadata.observer_company_id is not None
        and comparison.metadata.observer_company_id is not None
        and current.metadata.observer_company_id != comparison.metadata.observer_company_id
    ):
        raise AnalysisComparisonError("observer company changed between snapshots")
    limitations: tuple[str, ...] = ()
    if current.metadata.save_generation != comparison.metadata.save_generation:
        limitations = (
            "The comparison crosses a save/load generation; world identity remained stable.",
        )
    return ComparisonCompatibility(limitations=limitations)
