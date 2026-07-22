import json
from pathlib import Path

import pytest

from sim_pilot.game_bridge.models import FullSnapshotResponsePayload, parse_envelope
from sim_pilot.rail_route.bridge import (
    RailRouteBridgeObservationError,
    entity_from,
    render_entity,
    render_surface,
    surface_from,
)


def _snapshot():
    value = json.loads(
        Path("tests/fixtures/game_bridge/v2/full_snapshot_response.json").read_text()
    )
    value["protocol_version"] = 3
    value["adapter_version"] = "rail-route-ui-observer-v1"
    value["payload"]["snapshot"]["adapter_version"] = "rail-route-ui-observer-v1"
    envelope = parse_envelope(json.dumps(value).encode())
    assert isinstance(envelope.payload, FullSnapshotResponsePayload)
    return envelope.payload.snapshot


def test_surface_and_entity_queries_use_exact_semantic_identity() -> None:
    snapshot = _snapshot()

    surface = surface_from(snapshot, "trains")
    entity = entity_from(snapshot, "trains", "SP 101")

    assert entity.entity_id == "train:1"
    assert "trains: 1 entities" in render_surface(surface)
    assert '"display_name": "SP 101"' in render_entity(entity)


def test_query_rejects_unknown_or_unobserved_surface() -> None:
    snapshot = _snapshot()

    with pytest.raises(RailRouteBridgeObservationError, match="unknown Rail Route surface"):
        surface_from(snapshot, "money")
    with pytest.raises(RailRouteBridgeObservationError, match="is not observable"):
        surface_from(snapshot, "stations")
    with pytest.raises(RailRouteBridgeObservationError, match="omitted the surface"):
        surface_from(snapshot, "track-occupancy")


def test_query_rejects_missing_entity() -> None:
    with pytest.raises(RailRouteBridgeObservationError, match="no trains entity"):
        entity_from(_snapshot(), "trains", "missing")
