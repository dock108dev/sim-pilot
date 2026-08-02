from pathlib import Path

import pytest

from sim_pilot.software_inc.discovery import SoftwareIncDiscovery
from sim_pilot.software_inc.errors import SoftwareIncProbeInstallError
from sim_pilot.software_inc.probe import SoftwareIncProbeInstaller


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "SimPilotDiscoveryProbe.cs"
    source.write_text(
        "public class Probe : ModBehaviour { "
        "public override void OnActivate() {} public override void OnDeactivate() {} }",
        encoding="utf-8",
    )
    return source


def test_install_disable_and_uninstall_preserve_unknown_files(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path], tmp_path: Path
) -> None:
    discovery, game_root, state = software_inc_installation
    installer = SoftwareIncProbeInstaller(
        discovery=discovery, source_artifact=_source(tmp_path), state_directory=state
    )

    installed = installer.install()
    repeated = installer.install()
    assert installed.changed is True
    assert repeated.changed is False
    assert installer.manifest_path.stat().st_mode & 0o077 == 0
    assert installer.verify().manifest_valid is True

    target_directory = game_root / "DLLMods/SimPilotDiscoveryProbe"
    unknown = target_directory / "keep.txt"
    unknown.write_text("preserve", encoding="utf-8")
    assert installer.disable().changed is True
    result = installer.uninstall()

    assert result.changed is True
    assert unknown.read_text(encoding="utf-8") == "preserve"
    assert result.preserved_files == ("DLLMods/SimPilotDiscoveryProbe/keep.txt",)
    assert not installer.manifest_path.exists()


def test_uninstall_rejects_changed_owned_source(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path], tmp_path: Path
) -> None:
    discovery, game_root, state = software_inc_installation
    installer = SoftwareIncProbeInstaller(
        discovery=discovery, source_artifact=_source(tmp_path), state_directory=state
    )
    installer.install()
    (game_root / "DLLMods/SimPilotDiscoveryProbe/SimPilotDiscoveryProbe.cs").write_text(
        "changed", encoding="utf-8"
    )

    with pytest.raises(SoftwareIncProbeInstallError, match="refusing destructive"):
        installer.uninstall()


def test_install_rejects_running_game(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    discovery, _game_root, state = software_inc_installation

    def running_process(_path: Path) -> tuple[int, str, str]:
        return 123, "x86_64", "steam_osx"

    def running_window(_process_id: int) -> tuple[str, int, int, int, int, float]:
        return "Software Inc.", 0, 0, 1440, 900, 2.0

    monkeypatch.setattr(
        "sim_pilot.software_inc.discovery.macos.running_process",
        running_process,
    )
    monkeypatch.setattr(
        "sim_pilot.software_inc.discovery.macos.functional_screen_capture", lambda: True
    )
    monkeypatch.setattr(
        "sim_pilot.software_inc.discovery.macos.window_identity",
        running_window,
    )
    installer = SoftwareIncProbeInstaller(
        discovery=discovery, source_artifact=_source(tmp_path), state_directory=state
    )

    with pytest.raises(SoftwareIncProbeInstallError, match="running"):
        installer.install()


def test_install_rejects_broad_access_source(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path], tmp_path: Path
) -> None:
    discovery, _game_root, state = software_inc_installation
    source = _source(tmp_path)
    source.write_text("public static bool GiveMeFreedom = true;", encoding="utf-8")
    installer = SoftwareIncProbeInstaller(
        discovery=discovery, source_artifact=source, state_directory=state
    )

    with pytest.raises(SoftwareIncProbeInstallError, match="unrestricted"):
        installer.install()


def test_verify_rejects_managed_assembly_drift_but_uninstall_remains_available(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path], tmp_path: Path
) -> None:
    discovery, game_root, state = software_inc_installation
    installer = SoftwareIncProbeInstaller(
        discovery=discovery, source_artifact=_source(tmp_path), state_directory=state
    )
    installer.install()
    assembly = (
        game_root / "Software Inc.app/Contents/Resources/Data/Managed/Assembly-CSharp-firstpass.dll"
    )
    assembly.write_bytes(b"changed by fixture")

    with pytest.raises(SoftwareIncProbeInstallError, match="managed assemblies changed"):
        installer.verify()

    assert installer.uninstall().changed is True


def test_reinstall_rebuilds_only_known_game_generated_probe_cache(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path], tmp_path: Path
) -> None:
    discovery, game_root, state = software_inc_installation
    installer = SoftwareIncProbeInstaller(
        discovery=discovery, source_artifact=_source(tmp_path), state_directory=state
    )
    installer.install()
    target = game_root / "DLLMods/SimPilotDiscoveryProbe"
    (target / "SimPilotDiscoveryProbe.dcache").write_bytes(b"generated")
    (target / "SimPilotDiscoveryProbeH.bin").write_bytes(b"generated")
    installer.uninstall()

    reinstalled = installer.install()

    assert reinstalled.changed is True
    assert not (target / "SimPilotDiscoveryProbe.dcache").exists()
    assert not (target / "SimPilotDiscoveryProbeH.bin").exists()
    assert (target / "SimPilotDiscoveryProbe.cs").is_file()


def test_reinstall_rejects_unknown_leftover(
    software_inc_installation: tuple[SoftwareIncDiscovery, Path, Path], tmp_path: Path
) -> None:
    discovery, game_root, state = software_inc_installation
    installer = SoftwareIncProbeInstaller(
        discovery=discovery, source_artifact=_source(tmp_path), state_directory=state
    )
    target = game_root / "DLLMods/SimPilotDiscoveryProbe"
    target.mkdir(parents=True)
    (target / "unknown.dll").write_bytes(b"not owned")

    with pytest.raises(SoftwareIncProbeInstallError, match="unowned files"):
        installer.install()
