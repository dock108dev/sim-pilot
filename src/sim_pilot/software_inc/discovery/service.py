"""Compose truthful Software Inc. installation and official-mod evidence."""

from __future__ import annotations

import hashlib
import platform
import re
from pathlib import Path

from sim_pilot.software_inc.discovery.models import (
    AssemblyFingerprint,
    DiscoveryCoverage,
    DiscoveryStatus,
    Distribution,
    ScriptingBackend,
    SoftwareIncDiscoveryResult,
    SoftwareIncWindowIdentity,
)
from sim_pilot.software_inc.discovery.steam import software_inc_manifest
from sim_pilot.software_inc.errors import SoftwareIncDiscoveryError

PROBE_DIRECTORY_NAME = "SimPilotDiscoveryProbe"
PROBE_SOURCE_NAME = "SimPilotDiscoveryProbe.cs"
PROBE_DISABLED_NAME = "SimPilotDiscoveryProbe.cs.disabled"
PROBE_SETTING_NAME = "SimPilotDiscoveryProbeSetting.txt"
PROBE_MARKER = "SIM_PILOT_SOFTWARE_INC_PROBE"
_PROBE_EVENT = re.compile(
    rf"{PROBE_MARKER}\s+schema=1\s+event=(?P<event>[a-z_]+)\s+thread=(?P<thread>\d+)"
)
_PROBE_VERSION = re.compile(
    rf"{PROBE_MARKER}.*\sversion=(?P<version>\d+\.\d+\.\d+)\s+version_type=(?P<type>\d+)"
)


def repository_root() -> Path:
    return Path(__file__).resolve().parents[4]


def default_steamapps() -> Path:
    return Path.home() / "Library/Application Support/Steam/steamapps"


def default_state_directory() -> Path:
    return Path.home() / "Library/Application Support/Sim Pilot/software-inc/probe"


def probe_source_path() -> Path:
    return repository_root() / "software_inc_bridge/probe/SimPilotDiscoveryProbe.cs"


def save_path_candidates(game_root: Path | None = None) -> tuple[Path, ...]:
    support = Path.home() / "Library/Application Support"
    candidates = (
        support / "Software Inc",
        support / "Coredumping/Software Inc",
        support / "Coredumping/Software Inc.",
    )
    if game_root is None:
        return candidates
    return (game_root / "Saves", *candidates)


def player_log_candidates() -> tuple[Path, ...]:
    logs = Path.home() / "Library/Logs"
    return (
        logs / "Coredumping/Software Inc/Player.log",
        logs / "Coredumping/Software Inc./Player.log",
        logs / "Software Inc/Player.log",
        logs / "Unity/Player.log",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coverage(surface: str, status: DiscoveryStatus, detail: str) -> DiscoveryCoverage:
    return DiscoveryCoverage(surface=surface, status=status, detail=detail)


def current_player_log() -> Path | None:
    candidates: list[Path] = []
    for log in player_log_candidates():
        try:
            if log.is_file():
                candidates.append(log)
        except OSError:
            continue
    if not candidates:
        return None
    try:
        return max(candidates, key=lambda path: path.stat().st_mtime_ns)
    except OSError:
        return None


def _current_log_text() -> str:
    log = current_player_log()
    if log is None:
        return ""
    try:
        return log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def current_probe_loaded() -> bool:
    events = tuple(match.group("event") for match in _PROBE_EVENT.finditer(_current_log_text()))
    return bool(events) and events[-1] != "deactivated"


def current_probe_game_version() -> str | None:
    matches = tuple(_PROBE_VERSION.finditer(_current_log_text()))
    return matches[-1].group("version") if matches else None


class SoftwareIncDiscovery:
    """Inspect one local installation without changing game or save files."""

    def __init__(
        self,
        *,
        steamapps: Path | None = None,
        state_directory: Path | None = None,
        system: str | None = None,
    ) -> None:
        self.steamapps = (steamapps or default_steamapps()).expanduser()
        self.state_directory = (state_directory or default_state_directory()).expanduser()
        self.system = system or platform.system()

    def inspect(self) -> SoftwareIncDiscoveryResult:
        if self.system != "Darwin":
            return self._unsupported_platform()
        found = software_inc_manifest(self.steamapps)
        if found is None:
            return self._not_installed()
        manifest_path, manifest = found
        game_root = manifest_path.parent / "common" / manifest["installdir"]
        if game_root.is_symlink():
            raise SoftwareIncDiscoveryError("Software Inc. game root is a symlink")
        try:
            resolved_root = game_root.resolve(strict=True)
            resolved_common = (manifest_path.parent / "common").resolve(strict=True)
        except OSError as error:
            raise SoftwareIncDiscoveryError(
                f"Software Inc. installation path cannot be resolved: {error}"
            ) from error
        if resolved_root.parent != resolved_common:
            raise SoftwareIncDiscoveryError("Software Inc. installation escapes Steam common")

        app_candidates = sorted(resolved_root.glob("*.app"))
        preferred = resolved_root / "Software Inc.app"
        app_path = preferred if preferred.is_dir() else None
        if app_path is None and len(app_candidates) == 1:
            app_path = app_candidates[0]
        return self._inspect_macos_installation(
            game_root=resolved_root,
            app_path=app_path,
            steam_build_id=manifest.get("buildid"),
        )

    def _not_installed(self) -> SoftwareIncDiscoveryResult:
        candidates = save_path_candidates()
        return SoftwareIncDiscoveryResult(
            distribution=Distribution.UNKNOWN,
            installed=False,
            save_path_candidates=candidates,
            discovered_save_paths=tuple(path for path in candidates if path.exists()),
            probe_source_available=probe_source_path().is_file(),
            probe_installed=False,
            probe_enabled=False,
            probe_loaded=False,
            compatible=False,
            live_supported=False,
            reasons=("Software Inc. Steam app 362620 was not found in configured libraries",),
            coverage=(
                _coverage(
                    "installation",
                    DiscoveryStatus.UNAVAILABLE,
                    "Steam appmanifest_362620.acf was not found",
                ),
                _coverage(
                    "runtime",
                    DiscoveryStatus.NOT_APPLICABLE,
                    "runtime inspection requires an installation",
                ),
                _coverage(
                    "official_code_mod_api",
                    DiscoveryStatus.UNAVAILABLE,
                    "managed assemblies are not installed",
                ),
                _coverage(
                    "window",
                    DiscoveryStatus.NOT_APPLICABLE,
                    "window inspection requires a running installation",
                ),
                _coverage(
                    "probe_lifecycle",
                    DiscoveryStatus.UNAVAILABLE,
                    "the official probe cannot be installed without the game",
                ),
            ),
        )

    def _unsupported_platform(self) -> SoftwareIncDiscoveryResult:
        return SoftwareIncDiscoveryResult(
            distribution=Distribution.UNKNOWN,
            installed=False,
            probe_source_available=probe_source_path().is_file(),
            probe_installed=False,
            probe_enabled=False,
            probe_loaded=False,
            compatible=False,
            live_supported=False,
            reasons=(f"Software Inc. discovery is not implemented on {self.system}",),
            coverage=(
                _coverage(
                    "installation",
                    DiscoveryStatus.UNSUPPORTED,
                    f"{self.system} discovery is design-only in Prompt 1",
                ),
                _coverage("runtime", DiscoveryStatus.UNSUPPORTED, "runtime is unverified"),
                _coverage(
                    "official_code_mod_api", DiscoveryStatus.UNSUPPORTED, "runtime is unverified"
                ),
                _coverage("window", DiscoveryStatus.UNSUPPORTED, "runtime is unverified"),
                _coverage("probe_lifecycle", DiscoveryStatus.UNSUPPORTED, "runtime is unverified"),
            ),
        )

    def _inspect_macos_installation(
        self,
        *,
        game_root: Path,
        app_path: Path | None,
        steam_build_id: str | None,
    ) -> SoftwareIncDiscoveryResult:
        from sim_pilot.software_inc.discovery.macos import (
            accessibility_trusted,
            architectures,
            bundle_executable,
            bundle_info,
            functional_screen_capture,
            running_process,
            unity_version,
            window_identity,
        )

        coverage: list[DiscoveryCoverage] = []
        reasons: list[str] = []
        warnings: list[str] = []
        if app_path is None:
            reasons.append("Software Inc. application bundle was not found")
            coverage.append(_coverage("installation", DiscoveryStatus.FAILED, reasons[-1]))
            info: dict[str, object] = {}
            executable = None
        else:
            info = bundle_info(app_path)
            executable = bundle_executable(app_path, info)
            coverage.append(
                _coverage(
                    "installation",
                    DiscoveryStatus.OBSERVED,
                    f"Steam installation resolved to {game_root}",
                )
            )
        if executable is None:
            reasons.append("Software Inc. executable was not found")
        executable_architectures = () if executable is None else architectures(executable)
        process_id, running_architecture, parentage = (
            (None, None, None) if executable is None else running_process(executable)
        )
        running = process_id is not None
        coverage.append(
            _coverage(
                "runtime",
                DiscoveryStatus.OBSERVED if running else DiscoveryStatus.UNAVAILABLE,
                (
                    f"running process {process_id} was observed"
                    if running
                    else "the exact executable is not running"
                ),
            )
        )

        data_root = None if app_path is None else app_path / "Contents/Resources/Data"
        managed = None if data_root is None else data_root / "Managed"
        mono_assembly = None if managed is None else managed / "Assembly-CSharp.dll"
        il2cpp_metadata = (
            None if data_root is None else data_root / "il2cpp_data/Metadata/global-metadata.dat"
        )
        if mono_assembly is not None and mono_assembly.is_file():
            backend = ScriptingBackend.MONO
        elif il2cpp_metadata is not None and il2cpp_metadata.is_file():
            backend = ScriptingBackend.IL2CPP
            reasons.append("official managed code-mod probe requires Mono; found IL2CPP")
        else:
            backend = ScriptingBackend.UNKNOWN
            reasons.append("Unity scripting backend could not be established")

        fingerprints: list[AssemblyFingerprint] = []
        if managed is not None and managed.is_dir():
            for name in (
                "Assembly-CSharp.dll",
                "Assembly-CSharp-firstpass.dll",
                "UnityEngine.dll",
                "UnityEngine.CoreModule.dll",
            ):
                candidate = managed / name
                if candidate.is_file():
                    fingerprints.append(
                        AssemblyFingerprint(
                            name=name,
                            path=candidate,
                            sha256=_sha256(candidate),
                        )
                    )

        official_api = False
        if mono_assembly is not None and mono_assembly.is_file():
            payload = mono_assembly.read_bytes()
            official_api = b"ModMeta" in payload and b"ModBehaviour" in payload
        coverage.append(
            _coverage(
                "official_code_mod_api",
                DiscoveryStatus.OBSERVED if official_api else DiscoveryStatus.UNAVAILABLE,
                (
                    "ModMeta and ModBehaviour metadata markers were observed"
                    if official_api
                    else "required official code-mod type markers were not observed"
                ),
            )
        )
        if not official_api:
            reasons.append("official ModMeta/ModBehaviour API has not been verified")

        mod_root = game_root / "DLLMods"
        target = mod_root / PROBE_DIRECTORY_NAME
        enabled_probe = target / PROBE_SOURCE_NAME
        disabled_probe = target / PROBE_DISABLED_NAME
        probe_installed = enabled_probe.is_file() or disabled_probe.is_file()
        probe_enabled = enabled_probe.is_file() and not disabled_probe.exists()
        probe_loaded = running and probe_enabled and current_probe_loaded()
        probe_activation_setting = mod_root / PROBE_SETTING_NAME
        probe_activated = False
        if probe_activation_setting.is_file():
            try:
                probe_activated = "[Active]\nTrue" in probe_activation_setting.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                probe_activated = False
        proven_game_version = current_probe_game_version() if probe_loaded else None
        coverage.append(
            _coverage(
                "probe_lifecycle",
                DiscoveryStatus.OBSERVED if probe_loaded else DiscoveryStatus.UNAVAILABLE,
                (
                    "the current Unity log contains a Sim Pilot probe lifecycle marker"
                    if probe_loaded
                    else "the official probe has not been observed in the current runtime"
                ),
            )
        )

        trusted = accessibility_trusted()
        screen_capture = functional_screen_capture() if running else None
        raw_window = window_identity(process_id) if process_id is not None and trusted else None
        window = (
            None
            if raw_window is None or process_id is None
            else SoftwareIncWindowIdentity(
                process_id=process_id,
                title=raw_window[0],
                x=raw_window[1],
                y=raw_window[2],
                width=raw_window[3],
                height=raw_window[4],
                display_scale=raw_window[5],
            )
        )
        coverage.append(
            _coverage(
                "window",
                DiscoveryStatus.OBSERVED if window is not None else DiscoveryStatus.UNAVAILABLE,
                (
                    f"exact process window {window.title!r} and bounds were observed"
                    if window is not None
                    else "macOS Accessibility trust is required for exact window identity"
                    if running and not trusted
                    else "the exact process window could not be read"
                    if running
                    else "window inspection requires the game to be running"
                ),
            )
        )
        candidates = save_path_candidates(game_root)
        compatible = executable is not None and backend is ScriptingBackend.MONO and official_api
        if compatible and not probe_loaded:
            if running and probe_enabled and not probe_activated:
                warnings.append(
                    "enable SimPilotDiscoveryProbe once in Mods > Code mods to complete live proof"
                )
            else:
                warnings.append(
                    "installation is structurally compatible, but live support requires probe proof"
                )
        return SoftwareIncDiscoveryResult(
            distribution=Distribution.STEAM,
            installed=True,
            game_root=game_root,
            app_path=app_path,
            executable_path=executable,
            bundle_version=(
                str(info["CFBundleShortVersionString"])
                if "CFBundleShortVersionString" in info
                else None
            ),
            product_version=proven_game_version,
            steam_build_id=steam_build_id,
            executable_architectures=executable_architectures,
            running_architecture=running_architecture,
            unity_version=unity_version(info),
            scripting_backend=backend,
            managed_directory=managed if managed is not None and managed.is_dir() else None,
            assembly_fingerprints=tuple(fingerprints),
            official_code_mod_api_observed=official_api,
            mod_root=mod_root,
            save_path_candidates=candidates,
            discovered_save_paths=tuple(path for path in candidates if path.exists()),
            running=running,
            process_id=process_id,
            process_parentage=parentage,
            window=window,
            accessibility_trusted=trusted,
            screen_capture_functional=screen_capture,
            probe_source_available=probe_source_path().is_file(),
            probe_installed=probe_installed,
            probe_enabled=probe_enabled,
            probe_loaded=probe_loaded,
            compatible=compatible,
            live_supported=probe_loaded,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
            coverage=tuple(coverage),
        )
