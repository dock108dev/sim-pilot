import os
from pathlib import Path

import pytest

from sim_pilot.software_inc.discovery import (
    DiscoveryStatus,
    Distribution,
    ScriptingBackend,
    SoftwareIncDiscovery,
    service,
)
from sim_pilot.software_inc.errors import SoftwareIncDiscoveryError


def test_missing_installation_is_explicit(tmp_path: Path) -> None:
    result = SoftwareIncDiscovery(steamapps=tmp_path / "steamapps").inspect()

    assert result.installed is False
    assert result.distribution is Distribution.UNKNOWN
    assert result.compatible is False
    assert result.product_version is None
    assert result.steam_build_id is None
    assert result.coverage[0].status is DiscoveryStatus.UNAVAILABLE


def test_exact_mono_installation_is_discovered_without_version_guess(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path],
) -> None:
    discovery, game_root, _state = software_inc_installation

    result = discovery.inspect()

    assert result.installed is True
    assert result.game_root == game_root.resolve()
    assert result.bundle_version == "1.0"
    assert result.product_version is None
    assert result.steam_build_id == "fixture-build"
    assert result.unity_version == "2018.4.36f1"
    assert result.scripting_backend is ScriptingBackend.MONO
    assert result.executable_architectures == ("x86_64",)
    assert result.official_code_mod_api_observed is True
    assert result.compatible is True
    assert result.live_supported is False
    assert result.assembly_fingerprints
    assert result.game_root is not None
    assert result.save_path_candidates[0] == result.game_root / "Saves"
    assert not (result.game_root / "DLLMods").exists()


def test_probe_evidence_uses_current_log_and_respects_deactivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_log = tmp_path / "old.log"
    current_log = tmp_path / "current.log"
    old_log.write_text(
        "SIM_PILOT_SOFTWARE_INC_PROBE schema=1 event=activated thread=9 "
        "version=9.9.9 version_type=2\n",
        encoding="utf-8",
    )
    current_log.write_text(
        "SIM_PILOT_SOFTWARE_INC_PROBE schema=1 event=activated thread=1 "
        "version=1.8.41 version_type=2\n"
        "SIM_PILOT_SOFTWARE_INC_PROBE schema=1 event=deactivated thread=1 "
        "version=1.8.41 version_type=2\n",
        encoding="utf-8",
    )
    old_log.touch()
    current_log.touch()
    old_log.chmod(0o600)
    current_log.chmod(0o600)
    old_log_mtime = current_log.stat().st_mtime_ns - 1_000_000
    old_log.touch()
    os.utime(old_log, ns=(old_log_mtime, old_log_mtime))
    monkeypatch.setattr(service, "player_log_candidates", lambda: (old_log, current_log))

    assert service.current_player_log() == current_log
    assert service.current_probe_loaded() is False
    assert service.current_probe_game_version() == "1.8.41"


def test_unsafe_manifest_install_directory_is_rejected(tmp_path: Path) -> None:
    steamapps = tmp_path / "steamapps"
    steamapps.mkdir()
    (steamapps / "appmanifest_362620.acf").write_text(
        '"appid" "362620"\n"installdir" "../escape"\n', encoding="utf-8"
    )

    with pytest.raises(SoftwareIncDiscoveryError, match="unsafe"):
        SoftwareIncDiscovery(steamapps=steamapps).inspect()


def test_windows_remains_explicitly_unverified(tmp_path: Path) -> None:
    result = SoftwareIncDiscovery(steamapps=tmp_path, system="Windows").inspect()

    assert result.installed is False
    assert result.coverage[0].status is DiscoveryStatus.UNSUPPORTED
    assert "design-only" in result.coverage[0].detail
