"""Pinned, reversible BepInEx installation for the supported Rail Route build."""

from __future__ import annotations

import hashlib
import platform
import plistlib
import re
import secrets
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from contextlib import suppress
from pathlib import Path, PurePosixPath

from sim_pilot.private_files import atomic_write_private_text, ensure_private_directory
from sim_pilot.rail_route.discovery import DEFAULT_APP_PATH, STEAM_APP_ID, SUPPORTED_VERSION

from .errors import RailRouteBridgeCompatibilityError, RailRouteBridgeInstallError
from .models import (
    BridgeCompatibilityReport,
    BridgeInstallManifest,
    BridgeInstallResult,
    InstalledFileRecord,
)

SUPPORTED_STEAM_BUILD = "22547955"
SUPPORTED_UNITY_VERSION = "2021.3.45f2"
SUPPORTED_EXECUTABLE_SHA256 = "ef6ab0344cd13e95a8325c8a6f218b29d3735290d913a046eaf1015476d424c4"
SUPPORTED_ASSEMBLY_SHA256 = "93271ab49c8d8919dd258d981aa67767b99b4e352badaae8bb1d9c00d6659fcf"
LOADER_VERSION = "5.4.23.5"
LOADER_ARCHIVE_NAME = f"BepInEx_macos_universal_{LOADER_VERSION}.zip"
LOADER_URL = (
    f"https://github.com/BepInEx/BepInEx/releases/download/v{LOADER_VERSION}/{LOADER_ARCHIVE_NAME}"
)
LOADER_SHA256 = "01c2ae782eb016dfd6c345a18dbd2dcafffb3d9d318449d6486689f426b4a323"
PLUGIN_RELATIVE_PATH = Path("BepInEx/plugins/SimPilot.RailRoute.Bridge.dll")
DISABLED_PLUGIN_RELATIVE_PATH = PLUGIN_RELATIVE_PATH.with_suffix(".dll.disabled")
DEFAULT_PLUGIN_ARTIFACT = (
    Path(__file__).parents[4]
    / "rail_route_bridge/src/SimPilot.RailRoute.Bridge/bin/Release/netstandard2.0"
    / "SimPilot.RailRoute.Bridge.dll"
)
DEFAULT_STATE_DIRECTORY = Path.home() / "Library/Application Support/Sim Pilot/rail-route-bridge"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _architectures(path: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ["lipo", "-archs", str(path)], check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        return ()
    return tuple(sorted(completed.stdout.strip().split()))


class RailRouteBridgeInstaller:
    """Own only exact, recorded files under one validated Steam game directory."""

    def __init__(
        self,
        *,
        app_path: Path = DEFAULT_APP_PATH,
        plugin_artifact: Path = DEFAULT_PLUGIN_ARTIFACT,
        state_directory: Path = DEFAULT_STATE_DIRECTORY,
    ) -> None:
        self.app_path = app_path
        self.game_root = app_path.parent
        self.plugin_artifact = plugin_artifact
        self.state_directory = state_directory
        self.manifest_path = state_directory / "install-manifest.json"
        self.auth_token_path = state_directory / "auth-token"

    def diagnose(self) -> BridgeCompatibilityReport:
        reasons: list[str] = []
        if platform.system() != "Darwin":
            reasons.append("installation is implemented only for macOS; Windows is build-only")
        self._validate_paths(reasons)
        version, unity_version = self._versions(reasons)
        build = self._steam_build(reasons)
        executable = self.app_path / "Contents/MacOS/Rail Route"
        mono = self.app_path / "Contents/Frameworks/libmonobdwgc-2.0.dylib"
        assembly = self.app_path / "Contents/Resources/Data/Managed/RailRoute.dll"
        game_architectures = _architectures(executable) if executable.is_file() else ()
        if set(game_architectures) != {"arm64", "x86_64"}:
            reasons.append(
                f"expected universal game executable; found {game_architectures or 'none'}"
            )
        if not mono.is_file():
            reasons.append("Unity Mono runtime was not found")
        if executable.is_file() and _sha256(executable) != SUPPORTED_EXECUTABLE_SHA256:
            reasons.append("Rail Route executable hash differs from the live-proven build")
        if not assembly.is_file() or _sha256(assembly) != SUPPORTED_ASSEMBLY_SHA256:
            reasons.append("RailRoute.dll hash differs from the live-proven build")
        if self._game_running(executable):
            reasons.append("Rail Route is running; close it before changing bridge files")
        manifest = self._load_manifest(required=False)
        enabled = (self.game_root / PLUGIN_RELATIVE_PATH).is_file()
        installed = manifest is not None
        return BridgeCompatibilityReport(
            compatible=not reasons,
            game_root=self.game_root,
            app_path=self.app_path,
            game_version=version,
            steam_build_id=build,
            unity_version=unity_version,
            scripting_backend="mono" if mono.is_file() else "unknown",
            executable_architectures=game_architectures,
            loader_version=LOADER_VERSION,
            loader_architectures=("arm64", "x86_64"),
            plugin_artifact=self.plugin_artifact,
            plugin_available=self.plugin_artifact.is_file(),
            installed=installed,
            enabled=enabled,
            reasons=tuple(reasons),
        )

    def install(self, *, archive_path: Path | None = None) -> BridgeInstallResult:
        report = self.diagnose()
        if not report.compatible:
            raise RailRouteBridgeCompatibilityError("; ".join(report.reasons))
        if not self.plugin_artifact.is_file():
            raise RailRouteBridgeInstallError(
                f"bridge artifact missing at {self.plugin_artifact}; build the C# project first"
            )
        existing = self._load_manifest(required=False)
        if existing is not None:
            self._verify_owned_files(existing, allow_disabled=True)
            artifact_sha256 = _sha256(self.plugin_artifact)
            if existing.plugin_sha256 != artifact_sha256:
                return self._upgrade_owned_plugin(existing, artifact_sha256)
            if (self.game_root / DISABLED_PLUGIN_RELATIVE_PATH).is_file():
                disabled = self.game_root / DISABLED_PLUGIN_RELATIVE_PATH
                enabled = self.game_root / PLUGIN_RELATIVE_PATH
                disabled.replace(enabled)
                return BridgeInstallResult(
                    operation="install",
                    changed=True,
                    game_root=self.game_root,
                    affected_files=(str(PLUGIN_RELATIVE_PATH),),
                    message="existing verified bridge installation enabled",
                )
            return BridgeInstallResult(
                operation="install",
                changed=False,
                game_root=self.game_root,
                affected_files=(),
                message="verified bridge installation already present",
            )

        ensure_private_directory(self.state_directory)
        token_created = False
        if self.auth_token_path.exists():
            if (
                not self.auth_token_path.is_file()
                or stat.S_IMODE(self.auth_token_path.stat().st_mode) & 0o077
                or len(self.auth_token_path.read_text().strip()) < 32
            ):
                raise RailRouteBridgeInstallError("existing bridge authentication token is unsafe")
        else:
            atomic_write_private_text(self.auth_token_path, secrets.token_urlsafe(32) + "\n")
            token_created = True
        with tempfile.TemporaryDirectory(prefix="sim-pilot-rail-route-") as temporary:
            temporary_path = Path(temporary)
            archive = archive_path or temporary_path / LOADER_ARCHIVE_NAME
            if archive_path is None:
                urllib.request.urlretrieve(LOADER_URL, archive)
            if _sha256(archive) != LOADER_SHA256:
                raise RailRouteBridgeInstallError("BepInEx archive checksum does not match the pin")
            extraction = temporary_path / "loader"
            extraction.mkdir()
            files = self._extract_allowlisted(archive, extraction)
            plugin_target = extraction / PLUGIN_RELATIVE_PATH
            plugin_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.plugin_artifact, plugin_target)
            files.append(PLUGIN_RELATIVE_PATH)

            records: list[InstalledFileRecord] = []
            created: list[Path] = []
            try:
                for relative in sorted(files, key=lambda value: value.as_posix()):
                    source = extraction / relative
                    target = self._safe_target(relative)
                    if target.exists() or target.is_symlink():
                        raise RailRouteBridgeInstallError(
                            f"refusing to overwrite existing unowned path: {target}"
                        )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
                    target.chmod(source.stat().st_mode & 0o777)
                    created.append(target)
                    records.append(
                        InstalledFileRecord(
                            relative_path=relative.as_posix(), sha256=_sha256(target)
                        )
                    )
            except Exception:
                for target in reversed(created):
                    target.unlink(missing_ok=True)
                self._remove_empty_owned_directories()
                if token_created:
                    self.auth_token_path.unlink(missing_ok=True)
                raise
        manifest = BridgeInstallManifest(
            game_root=self.game_root.resolve(),
            app_path=self.app_path.resolve(),
            game_version=SUPPORTED_VERSION,
            steam_build_id=SUPPORTED_STEAM_BUILD,
            loader_version=LOADER_VERSION,
            loader_archive_sha256=LOADER_SHA256,
            plugin_sha256=_sha256(self.plugin_artifact),
            files=tuple(records),
        )
        try:
            atomic_write_private_text(self.manifest_path, manifest.model_dump_json(indent=2) + "\n")
        except Exception:
            for target in reversed(created):
                target.unlink(missing_ok=True)
            self._remove_empty_owned_directories()
            if token_created:
                self.auth_token_path.unlink(missing_ok=True)
            raise
        return BridgeInstallResult(
            operation="install",
            changed=True,
            game_root=self.game_root,
            affected_files=tuple(record.relative_path for record in records),
            message="installed pinned BepInEx loader and read-only UI-observer bridge",
        )

    def _upgrade_owned_plugin(
        self, manifest: BridgeInstallManifest, artifact_sha256: str
    ) -> BridgeInstallResult:
        """Replace only the verified owned plugin and atomically advance its checksum record."""
        enabled = self._safe_target(PLUGIN_RELATIVE_PATH)
        disabled = self._safe_target(DISABLED_PLUGIN_RELATIVE_PATH)
        target = disabled if disabled.is_file() and not enabled.exists() else enabled
        if not target.is_file():
            raise RailRouteBridgeInstallError("bridge plugin ownership state is inconsistent")

        with tempfile.NamedTemporaryFile(
            prefix=".sim-pilot-plugin-", suffix=".dll", dir=target.parent, delete=False
        ) as replacement_handle:
            replacement = Path(replacement_handle.name)
        with tempfile.NamedTemporaryFile(
            prefix=".sim-pilot-plugin-backup-", suffix=".dll", dir=target.parent, delete=False
        ) as backup_handle:
            backup = Path(backup_handle.name)
        try:
            shutil.copyfile(target, backup)
            shutil.copyfile(self.plugin_artifact, replacement)
            replacement.chmod(target.stat().st_mode & 0o777)
            if _sha256(replacement) != artifact_sha256:
                raise RailRouteBridgeInstallError("copied bridge artifact checksum is inconsistent")
            replacement.replace(target)
            updated_files = tuple(
                InstalledFileRecord(
                    relative_path=record.relative_path,
                    sha256=(
                        artifact_sha256
                        if record.relative_path == PLUGIN_RELATIVE_PATH.as_posix()
                        else record.sha256
                    ),
                )
                for record in manifest.files
            )
            updated = manifest.model_copy(
                update={"plugin_sha256": artifact_sha256, "files": updated_files}
            )
            try:
                atomic_write_private_text(
                    self.manifest_path, updated.model_dump_json(indent=2) + "\n"
                )
            except Exception:
                backup.replace(target)
                raise
            if target == disabled:
                disabled.replace(enabled)
        finally:
            replacement.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)
        return BridgeInstallResult(
            operation="install",
            changed=True,
            game_root=self.game_root,
            affected_files=(str(PLUGIN_RELATIVE_PATH),),
            message=(
                "upgraded verified owned plugin to the read-only UI-observer bridge and enabled it"
            ),
        )

    def verify(self) -> BridgeCompatibilityReport:
        report = self.diagnose()
        if not report.compatible:
            raise RailRouteBridgeCompatibilityError("; ".join(report.reasons))
        manifest = self._required_manifest()
        self._verify_owned_files(manifest, allow_disabled=True)
        return report

    def disable(self) -> BridgeInstallResult:
        manifest = self._required_manifest()
        self._verify_owned_files(manifest, allow_disabled=True)
        enabled = self._safe_target(PLUGIN_RELATIVE_PATH)
        disabled = self._safe_target(DISABLED_PLUGIN_RELATIVE_PATH)
        if disabled.is_file() and not enabled.exists():
            return BridgeInstallResult(
                operation="disable",
                changed=False,
                game_root=self.game_root,
                affected_files=(),
                message="bridge plugin is already disabled",
            )
        if not enabled.is_file() or disabled.exists():
            raise RailRouteBridgeInstallError("bridge plugin ownership state is inconsistent")
        enabled.replace(disabled)
        return BridgeInstallResult(
            operation="disable",
            changed=True,
            game_root=self.game_root,
            affected_files=(str(DISABLED_PLUGIN_RELATIVE_PATH),),
            message="bridge plugin disabled; the screen-control slice is unchanged",
        )

    def uninstall(self) -> BridgeInstallResult:
        manifest = self._required_manifest()
        self._verify_owned_files(manifest, allow_disabled=True)
        removed: list[str] = []
        for record in reversed(manifest.files):
            relative = Path(record.relative_path)
            target = self._safe_target(relative)
            if relative == PLUGIN_RELATIVE_PATH and not target.exists():
                target = self._safe_target(DISABLED_PLUGIN_RELATIVE_PATH)
            if target.is_file():
                target.unlink()
                removed.append(str(target.relative_to(self.game_root)))
        self._remove_empty_owned_directories()
        self.manifest_path.unlink()
        self.auth_token_path.unlink(missing_ok=True)
        with suppress(OSError):
            self.state_directory.rmdir()
        return BridgeInstallResult(
            operation="uninstall",
            changed=True,
            game_root=self.game_root,
            affected_files=tuple(removed),
            message=(
                "removed every unchanged manifest-owned file; generated or unrecognized files "
                "were preserved"
            ),
        )

    def _validate_paths(self, reasons: list[str]) -> None:
        if self.app_path.is_symlink() or self.game_root.is_symlink():
            reasons.append("game directory or application is a symlink")
        if not self.app_path.is_dir():
            reasons.append(f"Rail Route application not found at {self.app_path}")
            return
        try:
            if self.app_path.resolve().parent != self.game_root.resolve():
                reasons.append("resolved application escapes the Rail Route game directory")
        except OSError as error:
            reasons.append(f"unable to resolve application path: {error}")

    def _versions(self, reasons: list[str]) -> tuple[str, str]:
        info_path = self.app_path / "Contents/Info.plist"
        if not info_path.is_file():
            reasons.append("Info.plist is missing")
            return "unknown", "unknown"
        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
        version = str(info.get("CFBundleShortVersionString", "unknown"))
        info_string = str(info.get("CFBundleGetInfoString", ""))
        match = re.search(r"Unity Player version ([^ ]+)", info_string)
        unity = match.group(1) if match else "unknown"
        if version != SUPPORTED_VERSION:
            reasons.append(f"requires Rail Route {SUPPORTED_VERSION}; found {version}")
        if unity != SUPPORTED_UNITY_VERSION:
            reasons.append(f"requires Unity {SUPPORTED_UNITY_VERSION}; found {unity}")
        return version, unity

    def _steam_build(self, reasons: list[str]) -> str | None:
        manifest = self.game_root.parent.parent / f"appmanifest_{STEAM_APP_ID}.acf"
        if not manifest.is_file():
            reasons.append("Steam application manifest is missing")
            return None
        match = re.search(r'"buildid"\s+"(?P<build>\d+)"', manifest.read_text())
        build = match.group("build") if match else None
        if build != SUPPORTED_STEAM_BUILD:
            reasons.append(f"requires Steam build {SUPPORTED_STEAM_BUILD}; found {build}")
        return build

    @staticmethod
    def _game_running(executable: Path) -> bool:
        completed = subprocess.run(
            ["pgrep", "-f", str(executable)], check=False, capture_output=True, text=True
        )
        return completed.returncode == 0 and bool(completed.stdout.strip())

    def _extract_allowlisted(self, archive: Path, destination: Path) -> list[Path]:
        allowed_roots = {
            ".doorstop_version",
            "changelog.txt",
            "libdoorstop.dylib",
            "run_bepinex.sh",
        }
        extracted: list[Path] = []
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                pure = PurePosixPath(member.filename)
                relative = Path(*pure.parts)
                if (
                    pure.is_absolute()
                    or ".." in pure.parts
                    or (pure.parts[0] not in allowed_roots and pure.parts[0] != "BepInEx")
                ):
                    raise RailRouteBridgeInstallError(
                        f"loader archive contains unexpected path: {member.filename}"
                    )
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise RailRouteBridgeInstallError("loader archive contains a symlink")
                if member.is_dir():
                    continue
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(mode & 0o777 or 0o644)
                extracted.append(relative)
        if Path("libdoorstop.dylib") not in extracted or Path("run_bepinex.sh") not in extracted:
            raise RailRouteBridgeInstallError("loader archive is incomplete")
        if set(_architectures(destination / "libdoorstop.dylib")) != {"arm64", "x86_64"}:
            raise RailRouteBridgeInstallError("pinned loader is not the expected universal binary")
        return extracted

    def _safe_target(self, relative: Path) -> Path:
        if relative.is_absolute() or ".." in relative.parts:
            raise RailRouteBridgeInstallError(f"unsafe relative installation path: {relative}")
        target = self.game_root / relative
        parent = target.parent
        while parent != self.game_root:
            if parent.is_symlink():
                raise RailRouteBridgeInstallError(f"installation parent is a symlink: {parent}")
            parent = parent.parent
        if target.is_symlink():
            raise RailRouteBridgeInstallError(f"installation target is a symlink: {target}")
        return target

    def _load_manifest(self, *, required: bool) -> BridgeInstallManifest | None:
        if not self.manifest_path.is_file():
            if required:
                raise RailRouteBridgeInstallError(
                    "no Sim Pilot bridge installation manifest exists"
                )
            return None
        if stat.S_IMODE(self.manifest_path.stat().st_mode) & 0o077:
            raise RailRouteBridgeInstallError("installation manifest is not owner-only")
        try:
            manifest = BridgeInstallManifest.model_validate_json(self.manifest_path.read_text())
        except Exception as error:
            raise RailRouteBridgeInstallError("installation manifest is invalid") from error
        if (
            manifest.game_root != self.game_root.resolve()
            or manifest.app_path != self.app_path.resolve()
        ):
            raise RailRouteBridgeInstallError(
                "installation manifest targets another game directory"
            )
        return manifest

    def _required_manifest(self) -> BridgeInstallManifest:
        manifest = self._load_manifest(required=True)
        if manifest is None:  # Defensive narrowing; required=True raises above.
            raise RailRouteBridgeInstallError("no Sim Pilot bridge installation manifest exists")
        return manifest

    def _verify_owned_files(self, manifest: BridgeInstallManifest, *, allow_disabled: bool) -> None:
        for record in manifest.files:
            relative = Path(record.relative_path)
            target = self._safe_target(relative)
            if allow_disabled and relative == PLUGIN_RELATIVE_PATH and not target.exists():
                target = self._safe_target(DISABLED_PLUGIN_RELATIVE_PATH)
            if not target.is_file():
                raise RailRouteBridgeInstallError(f"manifest-owned file is missing: {target}")
            if _sha256(target) != record.sha256:
                raise RailRouteBridgeInstallError(
                    f"manifest-owned file changed; refusing destructive operation: {target}"
                )

    def _remove_empty_owned_directories(self) -> None:
        for relative in (
            Path("BepInEx/plugins"),
            Path("BepInEx/core"),
            Path("BepInEx"),
        ):
            directory = self.game_root / relative
            with suppress(OSError):
                directory.rmdir()
