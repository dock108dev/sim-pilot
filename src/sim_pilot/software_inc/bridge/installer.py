"""Checksum-gated compiled bridge installation for Software Inc."""

from __future__ import annotations

import hashlib
import os
import secrets
import stat
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from sim_pilot.private_files import atomic_write_private_text, ensure_private_directory
from sim_pilot.software_inc.discovery import SoftwareIncDiscovery
from sim_pilot.software_inc.discovery.service import current_player_log, repository_root
from sim_pilot.software_inc.errors import (
    SoftwareIncCompatibilityError,
    SoftwareIncProbeInstallError,
)

from .models import (
    BridgeInstallManifest,
    BridgeInstallResult,
    BridgeOwnedFile,
    SoftwareIncBridgeReport,
)

BRIDGE_DIRECTORY_NAME = "SimPilotBridge"
BRIDGE_FILE_NAME = "SimPilot.SoftwareInc.Bridge.dll"
BRIDGE_DISABLED_NAME = BRIDGE_FILE_NAME + ".disabled"
BRIDGE_MARKER = "SIM_PILOT_SOFTWARE_INC_BRIDGE"
DEFAULT_ARTIFACT = (
    repository_root() / "software_inc_bridge/bridge/bin/Release/net472" / BRIDGE_FILE_NAME
)
DEFAULT_STATE_DIRECTORY = Path.home() / "Library/Application Support/Sim Pilot/software-inc/bridge"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SoftwareIncBridgeInstaller:
    """Own exactly one compiled mod, its manifest, and an owner-only token."""

    def __init__(
        self,
        *,
        discovery: SoftwareIncDiscovery | None = None,
        artifact: Path = DEFAULT_ARTIFACT,
        state_directory: Path = DEFAULT_STATE_DIRECTORY,
    ) -> None:
        self.discovery = discovery or SoftwareIncDiscovery()
        self.artifact = artifact.expanduser()
        self.state_directory = state_directory.expanduser()
        self.manifest_path = self.state_directory / "install-manifest.json"
        self.auth_token_path = self.state_directory / "auth-token"

    def diagnose(self) -> SoftwareIncBridgeReport:
        discovered = self.discovery.inspect()
        manifest = self._load_manifest(required=False)
        artifact_sha = _sha256(self.artifact) if self.artifact.is_file() else None
        installed_sha = None
        enabled = False
        installed = manifest is not None
        reasons: list[str] = []
        if not discovered.installed:
            reasons.extend(discovered.reasons)
        if not self.artifact.is_file():
            reasons.append(f"bridge artifact missing at {self.artifact}")
        if discovered.running:
            reasons.append("Software Inc. is running; close it before changing bridge files")
        if manifest is not None:
            target = manifest.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_FILE_NAME
            disabled = manifest.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_DISABLED_NAME
            installed_target = target if target.is_file() else disabled
            if installed_target.is_file():
                installed_sha = _sha256(installed_target)
            enabled = target.is_file()
            try:
                self._verify_owned_file(manifest, allow_disabled=True)
                self._verify_identity(manifest, discovered)
            except SoftwareIncProbeInstallError as error:
                reasons.append(str(error))
        log = current_player_log()
        loaded = False
        if log is not None:
            with suppress(OSError):
                events = [
                    line
                    for line in log.read_text(encoding="utf-8", errors="replace").splitlines()
                    if BRIDGE_MARKER in line
                ]
                loaded = (
                    discovered.running and bool(events) and "event=deactivated" not in events[-1]
                )
        return SoftwareIncBridgeReport(
            discovery=discovered,
            artifact=self.artifact,
            artifact_available=self.artifact.is_file(),
            artifact_sha256=artifact_sha,
            installed_sha256=installed_sha,
            artifact_matches_installed=(
                None
                if artifact_sha is None or installed_sha is None
                else artifact_sha == installed_sha
            ),
            manifest_path=self.manifest_path,
            installed=installed,
            enabled=enabled,
            loaded=loaded,
            reasons=tuple(reasons),
        )

    def install(self, *, approve_broad_access: bool) -> BridgeInstallResult:
        if not approve_broad_access:
            raise SoftwareIncProbeInstallError(
                "compiled bridge needs Software Inc. GiveMeFreedom for owner-only token read "
                "and loopback networking; rerun with --approve-broad-access"
            )
        discovered = self.discovery.inspect()
        self._require_changeable(discovered)
        assert discovered.game_root is not None and discovered.mod_root is not None
        assert discovered.steam_build_id is not None
        if not self.artifact.is_file():
            raise SoftwareIncProbeInstallError(f"bridge artifact missing at {self.artifact}")
        existing = self._load_manifest(required=False)
        if existing is not None:
            self._verify_owned_file(existing, allow_disabled=True)
            self._verify_identity(existing, discovered)
            artifact_sha = _sha256(self.artifact)
            if existing.artifact_sha256 != artifact_sha:
                return self._upgrade_owned_bridge(existing, artifact_sha)
            enabled = existing.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_FILE_NAME
            disabled = existing.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_DISABLED_NAME
            if disabled.is_file() and not enabled.exists():
                disabled.replace(enabled)
                return self._result(
                    "install",
                    True,
                    existing.game_root,
                    (str(enabled.relative_to(existing.game_root)),),
                    "enabled the verified read-only bridge",
                )
            return self._result(
                "install",
                False,
                existing.game_root,
                (),
                "verified read-only bridge is already installed",
            )

        target_dir = self._safe_target_directory(discovered.game_root, discovered.mod_root)
        if target_dir.exists() and any(target_dir.iterdir()):
            raise SoftwareIncProbeInstallError("bridge target contains unowned files")
        ensure_private_directory(self.state_directory)
        if self.auth_token_path.exists():
            if (
                self.auth_token_path.is_symlink()
                or not self.auth_token_path.is_file()
                or stat.S_IMODE(self.auth_token_path.stat().st_mode) & 0o077
                or len(self.auth_token_path.read_text().strip()) < 32
            ):
                raise SoftwareIncProbeInstallError("existing bridge authentication token is unsafe")
        else:
            atomic_write_private_text(self.auth_token_path, secrets.token_urlsafe(32) + "\n")
        discovered.mod_root.mkdir(parents=True, exist_ok=True)
        target_dir.mkdir(mode=0o755, exist_ok=True)
        target = target_dir / BRIDGE_FILE_NAME
        temporary = target_dir / f".{BRIDGE_FILE_NAME}.{uuid4().hex}.tmp"
        try:
            temporary.write_bytes(self.artifact.read_bytes())
            temporary.chmod(0o644)
            os.replace(temporary, target)
            artifact_sha = _sha256(target)
            manifest = BridgeInstallManifest(
                game_root=discovered.game_root.resolve(),
                mod_root=discovered.mod_root.resolve(),
                artifact=self.artifact.resolve(),
                artifact_sha256=artifact_sha,
                product_version=discovered.product_version,
                steam_build_id=discovered.steam_build_id,
                assembly_fingerprints={
                    item.name: item.sha256 for item in discovered.assembly_fingerprints
                },
                installed_at=datetime.now(UTC),
                files=(
                    BridgeOwnedFile(
                        relative_path=f"{BRIDGE_DIRECTORY_NAME}/{BRIDGE_FILE_NAME}",
                        sha256=artifact_sha,
                    ),
                ),
            )
            atomic_write_private_text(self.manifest_path, manifest.model_dump_json(indent=2) + "\n")
        except Exception:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            with suppress(OSError):
                target_dir.rmdir()
            raise
        return self._result(
            "install",
            True,
            discovered.game_root,
            (str(target.relative_to(discovered.game_root)),),
            "installed the authenticated read-only bridge; enable it in Software Inc. "
            "and accept the documented access warning",
        )

    def _upgrade_owned_bridge(
        self, manifest: BridgeInstallManifest, artifact_sha256: str
    ) -> BridgeInstallResult:
        enabled = manifest.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_FILE_NAME
        disabled = manifest.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_DISABLED_NAME
        target = enabled if enabled.is_file() else disabled
        temporary = target.parent / f".{target.name}.{uuid4().hex}.tmp"
        backup = target.parent / f".{target.name}.{uuid4().hex}.backup"
        try:
            temporary.write_bytes(self.artifact.read_bytes())
            temporary.chmod(0o644)
            if _sha256(temporary) != artifact_sha256:
                raise SoftwareIncProbeInstallError("replacement bridge checksum changed")
            backup.write_bytes(target.read_bytes())
            backup.chmod(target.stat().st_mode & 0o777)
            os.replace(temporary, target)
            updated = manifest.model_copy(
                update={
                    "artifact": self.artifact.resolve(),
                    "artifact_sha256": artifact_sha256,
                    "installed_at": datetime.now(UTC),
                    "files": (
                        BridgeOwnedFile(
                            relative_path=f"{BRIDGE_DIRECTORY_NAME}/{BRIDGE_FILE_NAME}",
                            sha256=artifact_sha256,
                        ),
                    ),
                }
            )
            try:
                atomic_write_private_text(
                    self.manifest_path, updated.model_dump_json(indent=2) + "\n"
                )
            except Exception:
                os.replace(backup, target)
                raise
            backup.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)
        return self._result(
            "install",
            True,
            manifest.game_root,
            (str(target.relative_to(manifest.game_root)),),
            "upgraded the verified owned read-only bridge in place",
        )

    def verify(self) -> SoftwareIncBridgeReport:
        manifest = self._required_manifest()
        self._verify_owned_file(manifest, allow_disabled=True)
        self._verify_identity(manifest, self.discovery.inspect())
        if (
            self.auth_token_path.is_symlink()
            or not self.auth_token_path.is_file()
            or stat.S_IMODE(self.auth_token_path.stat().st_mode) & 0o077
        ):
            raise SoftwareIncProbeInstallError("bridge authentication token is missing or unsafe")
        return self.diagnose()

    def disable(self) -> BridgeInstallResult:
        discovered = self.discovery.inspect()
        if discovered.running:
            raise SoftwareIncProbeInstallError(
                "Software Inc. is running; close it before changing bridge files"
            )
        manifest = self._required_manifest()
        self._verify_owned_file(manifest, allow_disabled=True)
        enabled = manifest.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_FILE_NAME
        disabled = manifest.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_DISABLED_NAME
        if disabled.is_file() and not enabled.exists():
            return self._result(
                "disable", False, manifest.game_root, (), "read-only bridge is already disabled"
            )
        enabled.replace(disabled)
        return self._result(
            "disable",
            True,
            manifest.game_root,
            (str(disabled.relative_to(manifest.game_root)),),
            "disabled the read-only bridge",
        )

    def uninstall(self) -> BridgeInstallResult:
        discovered = self.discovery.inspect()
        if discovered.running:
            raise SoftwareIncProbeInstallError(
                "Software Inc. is running; close it before changing bridge files"
            )
        manifest = self._required_manifest()
        self._verify_owned_file(manifest, allow_disabled=True)
        directory = manifest.mod_root / BRIDGE_DIRECTORY_NAME
        enabled = directory / BRIDGE_FILE_NAME
        disabled = directory / BRIDGE_DISABLED_NAME
        target = enabled if enabled.is_file() else disabled
        target.unlink()
        preserved = tuple(
            str(path.relative_to(manifest.game_root))
            for path in sorted(directory.rglob("*"))
            if path.is_file()
        )
        if not preserved:
            directory.rmdir()
        self.manifest_path.unlink()
        self.auth_token_path.unlink(missing_ok=True)
        with suppress(OSError):
            self.state_directory.rmdir()
        return self._result(
            "uninstall",
            True,
            manifest.game_root,
            (str(target.relative_to(manifest.game_root)),),
            "removed the unchanged owned bridge and token; unrecognized files were preserved",
            preserved,
        )

    def _require_changeable(self, discovered: object) -> None:
        from sim_pilot.software_inc.discovery.models import SoftwareIncDiscoveryResult

        if not isinstance(discovered, SoftwareIncDiscoveryResult) or not discovered.installed:
            raise SoftwareIncCompatibilityError("Software Inc. is not installed")
        if discovered.running:
            raise SoftwareIncProbeInstallError(
                "Software Inc. is running; close it before changing bridge files"
            )
        if not discovered.compatible or discovered.game_root is None or discovered.mod_root is None:
            raise SoftwareIncCompatibilityError("Software Inc. installation is not compatible")

    @staticmethod
    def _safe_target_directory(game_root: Path, mod_root: Path) -> Path:
        if game_root.is_symlink() or mod_root.is_symlink():
            raise SoftwareIncProbeInstallError("game or mod root is a symlink")
        if mod_root.exists() and mod_root.resolve().parent != game_root.resolve():
            raise SoftwareIncProbeInstallError("DLLMods escapes the game root")
        target = mod_root / BRIDGE_DIRECTORY_NAME
        if target.is_symlink():
            raise SoftwareIncProbeInstallError("bridge target is a symlink")
        return target

    def _load_manifest(self, *, required: bool) -> BridgeInstallManifest | None:
        if not self.manifest_path.is_file():
            if required:
                raise SoftwareIncProbeInstallError("no bridge ownership manifest exists")
            return None
        if (
            self.manifest_path.is_symlink()
            or stat.S_IMODE(self.manifest_path.stat().st_mode) & 0o077
        ):
            raise SoftwareIncProbeInstallError("bridge ownership manifest is unsafe")
        try:
            return BridgeInstallManifest.model_validate_json(self.manifest_path.read_text())
        except Exception as error:
            raise SoftwareIncProbeInstallError("bridge ownership manifest is invalid") from error

    def _required_manifest(self) -> BridgeInstallManifest:
        manifest = self._load_manifest(required=True)
        assert manifest is not None
        return manifest

    @staticmethod
    def _verify_owned_file(manifest: BridgeInstallManifest, *, allow_disabled: bool) -> None:
        if (
            len(manifest.files) != 1
            or manifest.files[0].relative_path != f"{BRIDGE_DIRECTORY_NAME}/{BRIDGE_FILE_NAME}"
        ):
            raise SoftwareIncProbeInstallError("bridge manifest owns an unexpected path")
        enabled = manifest.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_FILE_NAME
        disabled = manifest.mod_root / BRIDGE_DIRECTORY_NAME / BRIDGE_DISABLED_NAME
        target = enabled if enabled.is_file() else disabled if allow_disabled else enabled
        if (
            target.is_symlink()
            or not target.is_file()
            or _sha256(target) != manifest.artifact_sha256
        ):
            raise SoftwareIncProbeInstallError("manifest-owned bridge is missing or changed")

    @staticmethod
    def _verify_identity(manifest: BridgeInstallManifest, discovered: object) -> None:
        from sim_pilot.software_inc.discovery.models import SoftwareIncDiscoveryResult

        if not isinstance(discovered, SoftwareIncDiscoveryResult):
            raise SoftwareIncProbeInstallError(
                "installed bridge identity no longer matches Software Inc."
            )
        product_changed = manifest.product_version is not None and (
            discovered.product_version != manifest.product_version
        )
        if (
            discovered.game_root != manifest.game_root
            or product_changed
            or discovered.steam_build_id != manifest.steam_build_id
        ):
            raise SoftwareIncProbeInstallError(
                "installed bridge identity no longer matches Software Inc."
            )
        current = {item.name: item.sha256 for item in discovered.assembly_fingerprints}
        if current != manifest.assembly_fingerprints:
            raise SoftwareIncProbeInstallError("Software Inc. managed assemblies changed")

    @staticmethod
    def _result(
        operation: Literal["install", "disable", "uninstall"],
        changed: bool,
        root: Path,
        affected: tuple[str, ...],
        message: str,
        preserved: tuple[str, ...] = (),
    ) -> BridgeInstallResult:
        return BridgeInstallResult(
            operation=operation,
            changed=changed,
            game_root=root,
            affected_files=affected,
            preserved_files=preserved,
            completed_at=datetime.now(UTC),
            message=message,
        )
