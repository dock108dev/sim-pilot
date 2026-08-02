from __future__ import annotations

import plistlib
from pathlib import Path

import pytest

from sim_pilot.software_inc.discovery import SoftwareIncDiscovery


@pytest.fixture
def software_inc_installation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[SoftwareIncDiscovery, Path, Path]:
    steamapps = tmp_path / "steamapps"
    game_root = steamapps / "common/Software Inc"
    app = game_root / "Software Inc.app"
    executable_directory = app / "Contents/MacOS"
    managed = app / "Contents/Resources/Data/Managed"
    executable_directory.mkdir(parents=True)
    managed.mkdir(parents=True)
    with (app / "Contents/Info.plist").open("wb") as stream:
        plistlib.dump(
            {
                "CFBundleExecutable": "Software Inc",
                "CFBundleShortVersionString": "1.0",
                "CFBundleGetInfoString": "Unity Player version 2018.4.36f1 (fixture)",
            },
            stream,
        )
    (executable_directory / "Software Inc").write_bytes(b"game")
    (managed / "Assembly-CSharp.dll").write_bytes(b"ModMeta\0ModBehaviour")
    (managed / "Assembly-CSharp-firstpass.dll").write_bytes(b"firstpass")
    steamapps.mkdir(parents=True, exist_ok=True)
    (steamapps / "appmanifest_362620.acf").write_text(
        '"AppState"\n{\n"appid" "362620"\n"buildid" "fixture-build"\n'
        '"installdir" "Software Inc"\n}\n',
        encoding="utf-8",
    )

    def fixture_architectures(_path: Path) -> tuple[str, ...]:
        return ("x86_64",)

    def fixture_process(_path: Path) -> tuple[None, None, None]:
        return None, None, None

    def fixture_window(
        _process_id: int,
    ) -> tuple[str, int, int, int, int, float] | None:
        return None

    monkeypatch.setattr(
        "sim_pilot.software_inc.discovery.macos.architectures", fixture_architectures
    )
    monkeypatch.setattr(
        "sim_pilot.software_inc.discovery.macos.running_process",
        fixture_process,
    )
    monkeypatch.setattr(
        "sim_pilot.software_inc.discovery.macos.accessibility_trusted", lambda: True
    )
    monkeypatch.setattr("sim_pilot.software_inc.discovery.macos.window_identity", fixture_window)
    state = tmp_path / "state"
    return SoftwareIncDiscovery(steamapps=steamapps, state_directory=state), game_root, state
