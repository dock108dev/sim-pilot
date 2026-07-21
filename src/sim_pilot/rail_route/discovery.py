"""Discover the local Steam Rail Route installation without mutating it."""

import plistlib
import re
import subprocess
from pathlib import Path

from sim_pilot.rail_route.errors import RailRouteDiscoveryError
from sim_pilot.rail_route.macos import accessibility_trusted
from sim_pilot.rail_route.models import RailRouteInstallation

SUPPORTED_VERSION = "2.3.24"
STEAM_APP_ID = "1124180"
DEFAULT_APP_PATH = (
    Path.home() / "Library/Application Support/Steam/steamapps/common/Rail Route/Rail Route.app"
)


class RailRouteDiscovery:
    """Resolve the exact local binary, build, process, and safety prerequisites."""

    def __init__(self, app_path: Path = DEFAULT_APP_PATH) -> None:
        self._app_path = app_path

    def inspect(self) -> RailRouteInstallation:
        info_path = self._app_path / "Contents/Info.plist"
        executable_path = self._app_path / "Contents/MacOS/Rail Route"
        if not info_path.is_file() or not executable_path.is_file():
            raise RailRouteDiscoveryError(f"Rail Route installation not found at {self._app_path}")

        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
        version = info.get("CFBundleShortVersionString")
        if not isinstance(version, str) or not version:
            raise RailRouteDiscoveryError("Rail Route version is missing from Info.plist")

        process_id = self._process_id(executable_path)
        build_id = self._steam_build_id()
        accessibility_enabled = self._accessibility_enabled()
        reasons: list[str] = []
        if version != SUPPORTED_VERSION:
            reasons.append(f"requires Rail Route {SUPPORTED_VERSION}; found {version}")
        if process_id is None:
            reasons.append("Rail Route is not running")
        if not accessibility_enabled:
            reasons.append("macOS Accessibility control is disabled")
        supported = not reasons
        return RailRouteInstallation(
            app_path=self._app_path,
            executable_path=executable_path,
            version=version,
            steam_app_id=STEAM_APP_ID,
            steam_build_id=build_id,
            process_id=process_id,
            running=process_id is not None,
            accessibility_enabled=accessibility_enabled,
            supported=supported,
            compatibility_reason="compatible" if supported else "; ".join(reasons),
        )

    @staticmethod
    def _process_id(executable_path: Path) -> int | None:
        completed = subprocess.run(
            ["pgrep", "-f", str(executable_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return None
        first = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
        return int(first) if first.isdigit() else None

    def _steam_build_id(self) -> str | None:
        manifest = self._app_path.parents[2] / f"appmanifest_{STEAM_APP_ID}.acf"
        if not manifest.is_file():
            return None
        match = re.search(r'"buildid"\s+"(?P<build_id>\d+)"', manifest.read_text())
        return None if match is None else match.group("build_id")

    @staticmethod
    def _accessibility_enabled() -> bool:
        """Read the native per-process Accessibility trust decision."""
        return accessibility_trusted()
