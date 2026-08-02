from __future__ import annotations

import hashlib
import plistlib
import stat
import zipfile
from pathlib import Path

import pytest

from sim_pilot.rail_route.bridge.errors import RailRouteBridgeInstallError
from sim_pilot.rail_route.bridge.installer import (
    LOADER_SHA256,
    PLUGIN_RELATIVE_PATH,
    SUPPORTED_ASSEMBLY_SHA256,
    SUPPORTED_EXECUTABLE_SHA256,
    RailRouteBridgeInstaller,
)


def _real_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[RailRouteBridgeInstaller, Path]:
    game_root = tmp_path / "steamapps/common/Rail Route"
    app = game_root / "Rail Route.app"
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/Frameworks").mkdir(parents=True)
    managed = app / "Contents/Resources/Data/Managed"
    managed.mkdir(parents=True)
    with (app / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump(
            {
                "CFBundleShortVersionString": "2.3.24",
                "CFBundleGetInfoString": "Unity Player version 2021.3.45f2 (fixture)",
            },
            stream,
        )
    executable = app / "Contents/MacOS/Rail Route"
    executable.write_bytes(b"game")
    (app / "Contents/Frameworks/libmonobdwgc-2.0.dylib").write_bytes(b"mono")
    (managed / "RailRoute.dll").write_bytes(b"assembly")
    manifest = game_root.parent.parent / "appmanifest_1124180.acf"
    manifest.write_text('"buildid" "22547955"')
    plugin = tmp_path / "SimPilot.RailRoute.Bridge.dll"
    plugin.write_bytes(b"plugin")
    state = tmp_path / "state"
    installer = RailRouteBridgeInstaller(
        app_path=app, plugin_artifact=plugin, state_directory=state
    )

    def fixture_sha(path: Path) -> str:
        if path.name == "Rail Route":
            return SUPPORTED_EXECUTABLE_SHA256
        if path.name == "RailRoute.dll":
            return SUPPORTED_ASSEMBLY_SHA256
        if path.suffix == ".zip":
            return LOADER_SHA256
        return _real_sha256(path)

    def fixture_architectures(_path: Path) -> tuple[str, ...]:
        return ("arm64", "x86_64")

    def fixture_game_running(_path: Path) -> bool:
        return False

    monkeypatch.setattr("sim_pilot.rail_route.bridge.installer._sha256", fixture_sha)
    monkeypatch.setattr(
        "sim_pilot.rail_route.bridge.installer._architectures", fixture_architectures
    )
    monkeypatch.setattr(
        RailRouteBridgeInstaller, "_game_running", staticmethod(fixture_game_running)
    )
    monkeypatch.setattr("sim_pilot.rail_route.bridge.installer.platform.system", lambda: "Darwin")
    return installer, tmp_path


def _loader_archive(path: Path) -> Path:
    archive = path / "loader.zip"
    with zipfile.ZipFile(archive, "w") as package:
        executable = zipfile.ZipInfo("run_bepinex.sh")
        executable.external_attr = (stat.S_IFREG | 0o755) << 16
        package.writestr(executable, b"#!/bin/sh\n")
        package.writestr("libdoorstop.dylib", b"loader")
        package.writestr("BepInEx/core/BepInEx.dll", b"core")
    return archive


def test_install_is_private_recorded_and_idempotent(
    installation: tuple[RailRouteBridgeInstaller, Path],
) -> None:
    installer, temporary = installation
    first = installer.install(archive_path=_loader_archive(temporary))
    second = installer.install(archive_path=_loader_archive(temporary))

    assert first.changed is True
    assert second.changed is False
    assert (installer.game_root / PLUGIN_RELATIVE_PATH).read_bytes() == b"plugin"
    assert stat.S_IMODE(installer.manifest_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(installer.auth_token_path.stat().st_mode) == 0o600
    assert installer.auth_token_path.read_text().strip() not in first.model_dump_json()


def test_install_checksum_gates_and_upgrades_only_the_owned_plugin(
    installation: tuple[RailRouteBridgeInstaller, Path],
) -> None:
    installer, temporary = installation
    installer.install(archive_path=_loader_archive(temporary))
    loader = installer.game_root / "BepInEx/core/BepInEx.dll"
    loader_before = loader.read_bytes()
    installer.plugin_artifact.write_bytes(b"plugin-v2")

    result = installer.install(archive_path=_loader_archive(temporary))

    assert result.changed is True
    assert result.affected_files == (PLUGIN_RELATIVE_PATH.as_posix(),)
    assert (installer.game_root / PLUGIN_RELATIVE_PATH).read_bytes() == b"plugin-v2"
    assert loader.read_bytes() == loader_before
    assert installer.verify().installed is True


def test_disable_then_uninstall_removes_only_owned_files(
    installation: tuple[RailRouteBridgeInstaller, Path],
) -> None:
    installer, temporary = installation
    installer.install(archive_path=_loader_archive(temporary))
    generated = installer.game_root / "BepInEx/config/generated.cfg"
    generated.parent.mkdir(parents=True)
    generated.write_text("preserve")

    assert installer.disable().changed is True
    result = installer.uninstall()

    assert result.changed is True
    assert generated.read_text() == "preserve"
    assert not installer.manifest_path.exists()
    assert not installer.auth_token_path.exists()


def test_uninstall_refuses_a_modified_owned_file(
    installation: tuple[RailRouteBridgeInstaller, Path],
) -> None:
    installer, temporary = installation
    installer.install(archive_path=_loader_archive(temporary))
    (installer.game_root / "BepInEx/core/BepInEx.dll").write_bytes(b"changed")

    with pytest.raises(RailRouteBridgeInstallError, match="refusing destructive operation"):
        installer.uninstall()


def test_install_rejects_archive_traversal(
    installation: tuple[RailRouteBridgeInstaller, Path],
) -> None:
    installer, temporary = installation
    archive = temporary / "bad.zip"
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("../escape", b"bad")

    with pytest.raises(RailRouteBridgeInstallError, match="unexpected path"):
        installer.install(archive_path=archive)


def test_diagnose_rejects_non_macos_platform(
    installation: tuple[RailRouteBridgeInstaller, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    installer, _temporary = installation
    monkeypatch.setattr("sim_pilot.rail_route.bridge.installer.platform.system", lambda: "Linux")

    report = installer.diagnose()

    assert report.compatible is False
    assert any("installation is implemented only for macOS" in reason for reason in report.reasons)
