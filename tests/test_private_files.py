"""Owner-only atomic file helper behavior."""

import stat
from pathlib import Path

from sim_pilot.private_files import atomic_write_private_text


def test_atomic_private_write_creates_and_replaces_owner_only_file(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts"
    path = directory / "result.json"

    atomic_write_private_text(path, "first\n")
    atomic_write_private_text(path, "second\n")

    assert path.read_text(encoding="utf-8") == "second\n"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not tuple(directory.glob(".*.tmp"))
