"""Fail-closed Steam library and app-manifest parsing for Software Inc."""

import re
from pathlib import Path

from sim_pilot.software_inc.errors import SoftwareIncDiscoveryError
from sim_pilot.software_inc.models import STEAM_APP_ID

_PAIR = re.compile(r'^\s*"(?P<key>[^"]+)"\s+"(?P<value>(?:\\.|[^"])*)"\s*$')


def parse_acf_pairs(text: str) -> dict[str, str]:
    """Parse the scalar pairs needed from Valve's text VDF/ACF format."""
    pairs: dict[str, str] = {}
    for line in text.splitlines():
        match = _PAIR.match(line)
        if match is None:
            continue
        value = match.group("value").replace(r"\\", "\\").replace(r"\"", '"')
        pairs[match.group("key")] = value
    return pairs


def steamapps_directories(default_steamapps: Path) -> tuple[Path, ...]:
    """Return configured Steam library app roots in stable order."""
    directories: list[Path] = [default_steamapps]
    libraries = default_steamapps / "libraryfolders.vdf"
    if libraries.is_file():
        for line in libraries.read_text(encoding="utf-8", errors="replace").splitlines():
            match = _PAIR.match(line)
            if match is None or match.group("key") != "path":
                continue
            root = Path(match.group("value").replace(r"\\", "\\")).expanduser()
            candidate = root / "steamapps"
            if candidate not in directories:
                directories.append(candidate)
    return tuple(directories)


def software_inc_manifest(default_steamapps: Path) -> tuple[Path, dict[str, str]] | None:
    """Find and parse the Software Inc. Steam manifest without guessing a build."""
    for steamapps in steamapps_directories(default_steamapps):
        manifest = steamapps / f"appmanifest_{STEAM_APP_ID}.acf"
        if not manifest.is_file():
            continue
        pairs = parse_acf_pairs(manifest.read_text(encoding="utf-8", errors="strict"))
        if pairs.get("appid") not in {None, STEAM_APP_ID}:
            raise SoftwareIncDiscoveryError("Steam manifest app ID does not match 362620")
        install_dir = pairs.get("installdir")
        if install_dir is None:
            raise SoftwareIncDiscoveryError("Steam manifest has no installdir")
        relative = Path(install_dir)
        if relative.is_absolute() or len(relative.parts) != 1 or ".." in relative.parts:
            raise SoftwareIncDiscoveryError("Steam manifest installdir is unsafe")
        return manifest, pairs
    return None
