from pathlib import Path

import pytest

from sim_pilot.software_inc.bridge.installer import (
    BRIDGE_DIRECTORY_NAME,
    BRIDGE_DISABLED_NAME,
    BRIDGE_FILE_NAME,
    SoftwareIncBridgeInstaller,
)
from sim_pilot.software_inc.errors import SoftwareIncProbeInstallError


def test_bridge_install_requires_explicit_broad_access_approval(
    software_inc_installation: tuple[object, Path, Path], tmp_path: Path
) -> None:
    discovery, _root, _ = software_inc_installation
    artifact = tmp_path / BRIDGE_FILE_NAME
    artifact.write_bytes(b"compiled-read-only-bridge")
    installer = SoftwareIncBridgeInstaller(
        discovery=discovery,  # type: ignore[arg-type]
        artifact=artifact,
        state_directory=tmp_path / "bridge-state",
    )

    with pytest.raises(SoftwareIncProbeInstallError, match="approve-broad-access"):
        installer.install(approve_broad_access=False)

    assert not (tmp_path / "bridge-state/auth-token").exists()


def test_bridge_lifecycle_is_checksum_gated_and_reversible(
    software_inc_installation: tuple[object, Path, Path], tmp_path: Path
) -> None:
    discovery, game_root, _ = software_inc_installation
    artifact = tmp_path / BRIDGE_FILE_NAME
    artifact.write_bytes(b"compiled-read-only-bridge")
    state = tmp_path / "bridge-state"
    installer = SoftwareIncBridgeInstaller(
        discovery=discovery,  # type: ignore[arg-type]
        artifact=artifact,
        state_directory=state,
    )

    installed = installer.install(approve_broad_access=True)
    target = game_root / "DLLMods" / BRIDGE_DIRECTORY_NAME / BRIDGE_FILE_NAME

    assert installed.changed
    assert target.read_bytes() == artifact.read_bytes()
    assert state.stat().st_mode & 0o077 == 0
    assert (state / "auth-token").stat().st_mode & 0o077 == 0
    assert installer.verify().enabled

    assert installer.disable().changed
    assert not target.exists()
    assert (target.parent / BRIDGE_DISABLED_NAME).is_file()

    assert installer.install(approve_broad_access=True).changed
    unknown = target.parent / "keep.txt"
    unknown.write_text("user file")
    removed = installer.uninstall()

    assert unknown.is_file()
    assert str(unknown.relative_to(game_root)) in removed.preserved_files
    assert not (state / "auth-token").exists()


def test_bridge_verify_rejects_modified_owned_dll(
    software_inc_installation: tuple[object, Path, Path], tmp_path: Path
) -> None:
    discovery, game_root, _ = software_inc_installation
    artifact = tmp_path / BRIDGE_FILE_NAME
    artifact.write_bytes(b"compiled-read-only-bridge")
    installer = SoftwareIncBridgeInstaller(
        discovery=discovery,  # type: ignore[arg-type]
        artifact=artifact,
        state_directory=tmp_path / "bridge-state",
    )
    installer.install(approve_broad_access=True)
    target = game_root / "DLLMods" / BRIDGE_DIRECTORY_NAME / BRIDGE_FILE_NAME
    target.write_bytes(b"changed")

    with pytest.raises(SoftwareIncProbeInstallError, match="missing or changed"):
        installer.verify()


def test_bridge_install_atomically_upgrades_a_verified_owned_dll(
    software_inc_installation: tuple[object, Path, Path], tmp_path: Path
) -> None:
    discovery, game_root, _ = software_inc_installation
    artifact = tmp_path / BRIDGE_FILE_NAME
    artifact.write_bytes(b"first-build")
    installer = SoftwareIncBridgeInstaller(
        discovery=discovery,  # type: ignore[arg-type]
        artifact=artifact,
        state_directory=tmp_path / "bridge-state",
    )
    installer.install(approve_broad_access=True)
    token_before = installer.auth_token_path.read_bytes()
    artifact.write_bytes(b"unity-mono-build")

    upgraded = installer.install(approve_broad_access=True)
    target = game_root / "DLLMods" / BRIDGE_DIRECTORY_NAME / BRIDGE_FILE_NAME

    assert upgraded.changed
    assert "upgraded" in upgraded.message
    assert target.read_bytes() == b"unity-mono-build"
    assert installer.auth_token_path.read_bytes() == token_before
    assert installer.verify().enabled


def test_bridge_diagnose_does_not_treat_stale_log_as_loaded_when_game_is_stopped(
    software_inc_installation: tuple[object, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, _game_root, _ = software_inc_installation
    artifact = tmp_path / BRIDGE_FILE_NAME
    artifact.write_bytes(b"compiled-read-only-bridge")
    installer = SoftwareIncBridgeInstaller(
        discovery=discovery,  # type: ignore[arg-type]
        artifact=artifact,
        state_directory=tmp_path / "bridge-state",
    )
    installer.install(approve_broad_access=True)
    stale_log = tmp_path / "Player.log"
    stale_log.write_text(
        "SIM_PILOT_SOFTWARE_INC_BRIDGE schema=1 event=activated authority=read_only_loopback\n"
    )
    monkeypatch.setattr(
        "sim_pilot.software_inc.bridge.installer.current_player_log", lambda: stale_log
    )

    assert not installer.diagnose().loaded
