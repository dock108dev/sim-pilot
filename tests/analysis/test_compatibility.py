import pytest

from sim_pilot.analysis.compatibility import validate_comparison
from sim_pilot.analysis.errors import AnalysisComparisonError
from tests.analysis.helpers import snapshot


def test_compatible_save_generation_change_is_disclosed() -> None:
    current = snapshot(save_generation=3)
    comparison = snapshot("snapshot-previous", game_date=10, save_generation=2)

    result = validate_comparison(
        current,
        comparison,
        expected_snapshot_id=comparison.metadata.snapshot_id,
    )

    assert "save/load generation" in result.limitations[0]


@pytest.mark.parametrize(
    ("current", "comparison", "message"),
    (
        (snapshot(), snapshot("previous", world_id="world-2"), "different worlds"),
        (
            snapshot(),
            snapshot("previous", capability_fingerprint="different"),
            "different capabilities",
        ),
        (snapshot(complete=False), snapshot("previous"), "complete snapshots"),
        (snapshot(game_date=5), snapshot("previous", game_date=10), "must not be newer"),
        (
            snapshot(observer_company_id="company-1"),
            snapshot("previous", observer_company_id="company-2"),
            "observer company changed",
        ),
    ),
)
def test_incompatible_comparisons_fail_closed(
    current: object, comparison: object, message: str
) -> None:
    with pytest.raises(AnalysisComparisonError, match=message):
        validate_comparison(
            current,  # type: ignore[arg-type]
            comparison,  # type: ignore[arg-type]
            expected_snapshot_id=comparison.metadata.snapshot_id,  # type: ignore[attr-defined]
        )
