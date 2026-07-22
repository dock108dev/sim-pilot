import json
import hashlib
from pathlib import Path


def test_test_yard_manifest_has_deterministic_required_relationships() -> None:
    manifest = json.loads(Path("tests/fixtures/rail_route/test_yard/v1/manifest.json").read_text())

    assert manifest["display_name"] == "Sim Pilot Test Yard"
    assert manifest["layout"]["signals_left_to_right"] == [
        "SIG-C-W",
        "SIG-W-IN",
        "SIG-C-E",
        "SIG-E-IN",
    ]
    assert manifest["layout"]["stations"] == []
    assert manifest["layout"]["trains"] == []
    assert manifest["initial_time"] == "08:00:00"
    assert manifest["initial_paused"] is True
    assert manifest["set_route"] == {
        "origin_signal": "SIG-W-IN",
        "destination_signal": "SIG-C-W",
        "expected_unique_path": True,
        "initially_free": True,
    }
    assert {case["kind"] for case in manifest["negative_assertions"]} == {
        "same_signal",
        "missing_destination",
        "already_allocated",
    }
    artifact = manifest["artifact"]
    assert artifact["status"] == "created"
    assert artifact["relative_path"] == "artifact"
    assert artifact["windows_verified"] is False
    artifact_root = Path("tests/fixtures/rail_route/test_yard/v1/artifact")
    for expected in artifact["files"]:
        contents = (artifact_root / expected["name"]).read_bytes()
        assert hashlib.sha256(contents).hexdigest() == expected["sha256"]
