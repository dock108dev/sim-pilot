"""Checksum-gated official code-mod probe installation and recovery."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sim_pilot.software_inc.discovery.service import (
    PROBE_DIRECTORY_NAME,
    PROBE_DISABLED_NAME,
    PROBE_MARKER,
    PROBE_SOURCE_NAME,
    SoftwareIncDiscovery,
    current_player_log,
    default_state_directory,
    probe_source_path,
)
from sim_pilot.software_inc.errors import (
    SoftwareIncCompatibilityError,
    SoftwareIncProbeInstallError,
)
from sim_pilot.software_inc.probe.models import (
    ProbeInstallManifest,
    ProbeInstallResult,
    ProbeOwnedFile,
    SoftwareIncProbeReport,
)

_LIFECYCLE = re.compile(
    rf"{PROBE_MARKER}\s+schema=1\s+event=(?P<event>[a-z_]+)\s+thread=(?P<thread>\d+)"
)
_GENERATED_PROBE_FILES = {
    "SimPilotDiscoveryProbe.dcache",
    "SimPilotDiscoveryProbeH.bin",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SoftwareIncProbeInstaller:
    """Install only the official source probe and retain exact ownership."""

    def __init__(
        self,
        *,
        discovery: SoftwareIncDiscovery | None = None,
        source_artifact: Path | None = None,
        state_directory: Path | None = None,
    ) -> None:
        self.discovery = discovery or SoftwareIncDiscovery()
        self.source_artifact = (source_artifact or probe_source_path()).expanduser()
        self.state_directory = (state_directory or default_state_directory()).expanduser()
        self.manifest_path = self.state_directory / "install-manifest.json"

    def diagnose(self) -> SoftwareIncProbeReport:
        discovered = self.discovery.inspect()
        source_sha = _sha256(self.source_artifact) if self.source_artifact.is_file() else None
        source_text = (
            self.source_artifact.read_text(encoding="utf-8")
            if self.source_artifact.is_file()
            else ""
        )
        manifest = self._load_manifest(required=False)
        installed = discovered.probe_installed
        enabled = discovered.probe_enabled
        events, threads = self._lifecycle_evidence()
        reasons: list[str] = []
        manifest_valid = False
        if not discovered.installed:
            reasons.extend(discovered.reasons)
        if not self.source_artifact.is_file():
            reasons.append("official probe source artifact is missing")
        if manifest is not None:
            try:
                self._verify_owned_file(manifest, allow_disabled=True)
                self._verify_manifest_identity(manifest, discovered)
                manifest_valid = True
            except SoftwareIncProbeInstallError as error:
                reasons.append(str(error))
        return SoftwareIncProbeReport(
            discovery=discovered,
            source_sha256=source_sha,
            manifest_path=self.manifest_path,
            manifest_valid=manifest_valid,
            installed=installed,
            enabled=enabled,
            loaded=discovered.probe_loaded and bool(events),
            lifecycle_events=events,
            lifecycle_thread_ids=threads,
            broad_access_requested="GiveMeFreedom" in source_text,
            save_serialization_declared=(
                "Serialize(" in source_text or "Deserialize(" in source_text
            ),
            reasons=tuple(reasons),
        )

    def install(self) -> ProbeInstallResult:
        discovered = self.discovery.inspect()
        self._require_installable(discovered)
        assert discovered.game_root is not None
        assert discovered.mod_root is not None
        if not self.source_artifact.is_file():
            raise SoftwareIncProbeInstallError("official probe source artifact is missing")
        source_text = self.source_artifact.read_text(encoding="utf-8")
        if "GiveMeFreedom" in source_text:
            raise SoftwareIncProbeInstallError(
                "probe requests unrestricted mod access; explicit approval is required"
            )
        if "Serialize(" in source_text or "Deserialize(" in source_text:
            raise SoftwareIncProbeInstallError("probe must not declare custom save serialization")

        existing = self._load_manifest(required=False)
        if existing is not None:
            self._verify_owned_file(existing, allow_disabled=True)
            self._verify_manifest_identity(existing, discovered)
            return ProbeInstallResult(
                operation="install",
                changed=False,
                game_root=discovered.game_root,
                affected_files=(),
                completed_at=datetime.now(UTC),
                message="official Software Inc. discovery probe is already installed",
            )

        mod_root = discovered.mod_root
        target_directory = self._safe_target_directory(discovered.game_root, mod_root)
        generated_files: tuple[Path, ...] = ()
        if target_directory.exists():
            occupants = tuple(target_directory.iterdir())
            unexpected = tuple(
                path
                for path in occupants
                if path.name not in _GENERATED_PROBE_FILES
                or path.is_symlink()
                or not path.is_file()
            )
            if unexpected:
                raise SoftwareIncProbeInstallError(
                    "probe target contains unowned files; refusing installation"
                )
            generated_files = occupants
            for generated in generated_files:
                generated.unlink()
        mod_root.mkdir(parents=True, exist_ok=True)
        target_directory.mkdir(mode=0o755, parents=False, exist_ok=True)
        target = target_directory / PROBE_SOURCE_NAME
        source_sha = _sha256(self.source_artifact)
        temporary = target_directory / f".{PROBE_SOURCE_NAME}.{uuid4().hex}.tmp"
        try:
            temporary.write_bytes(self.source_artifact.read_bytes())
            temporary.chmod(0o644)
            os.replace(temporary, target)
            manifest = ProbeInstallManifest(
                game_root=discovered.game_root.resolve(),
                mod_root=mod_root.resolve(),
                source_artifact=self.source_artifact.resolve(),
                source_sha256=source_sha,
                product_version=discovered.product_version,
                steam_build_id=discovered.steam_build_id,
                assembly_fingerprints={
                    item.name: item.sha256 for item in discovered.assembly_fingerprints
                },
                installed_at=datetime.now(UTC),
                files=(
                    ProbeOwnedFile(
                        relative_path=f"{PROBE_DIRECTORY_NAME}/{PROBE_SOURCE_NAME}",
                        sha256=source_sha,
                    ),
                ),
            )
            self._write_manifest(manifest)
        except Exception:
            temporary.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            with suppress(OSError):
                target_directory.rmdir()
            raise
        return ProbeInstallResult(
            operation="install",
            changed=True,
            game_root=discovered.game_root,
            affected_files=(
                f"DLLMods/{PROBE_DIRECTORY_NAME}/{PROBE_SOURCE_NAME}",
                *(
                    f"DLLMods/{PROBE_DIRECTORY_NAME}/{generated.name}"
                    for generated in generated_files
                ),
            ),
            completed_at=datetime.now(UTC),
            message="installed the read-only official Software Inc. lifecycle probe",
        )

    def verify(self) -> SoftwareIncProbeReport:
        manifest = self._required_manifest()
        self._verify_owned_file(manifest, allow_disabled=True)
        self._verify_manifest_identity(manifest, self.discovery.inspect())
        report = self.diagnose()
        if report.broad_access_requested or report.save_serialization_declared:
            raise SoftwareIncProbeInstallError("installed probe violates the Prompt 1 boundary")
        return report

    def disable(self) -> ProbeInstallResult:
        discovered = self.discovery.inspect()
        if discovered.running:
            raise SoftwareIncProbeInstallError(
                "Software Inc. is running; close it before changing probe files"
            )
        manifest = self._required_manifest()
        source = manifest.mod_root / PROBE_DIRECTORY_NAME / PROBE_SOURCE_NAME
        disabled = manifest.mod_root / PROBE_DIRECTORY_NAME / PROBE_DISABLED_NAME
        self._verify_owned_file(manifest, allow_disabled=True)
        if disabled.is_file() and not source.exists():
            return ProbeInstallResult(
                operation="disable",
                changed=False,
                game_root=manifest.game_root,
                affected_files=(),
                completed_at=datetime.now(UTC),
                message="official Software Inc. discovery probe is already disabled",
            )
        if not source.is_file() or disabled.exists():
            raise SoftwareIncProbeInstallError("probe ownership state is inconsistent")
        source.replace(disabled)
        return ProbeInstallResult(
            operation="disable",
            changed=True,
            game_root=manifest.game_root,
            affected_files=(f"DLLMods/{PROBE_DIRECTORY_NAME}/{PROBE_DISABLED_NAME}",),
            completed_at=datetime.now(UTC),
            message="disabled the official Software Inc. discovery probe",
        )

    def uninstall(self) -> ProbeInstallResult:
        discovered = self.discovery.inspect()
        if discovered.running:
            raise SoftwareIncProbeInstallError(
                "Software Inc. is running; close it before changing probe files"
            )
        manifest = self._required_manifest()
        target_directory = manifest.mod_root / PROBE_DIRECTORY_NAME
        self._verify_owned_file(manifest, allow_disabled=True)
        source = target_directory / PROBE_SOURCE_NAME
        disabled = target_directory / PROBE_DISABLED_NAME
        target = source if source.is_file() else disabled
        target.unlink()
        preserved = tuple(
            str(path.relative_to(manifest.game_root))
            for path in sorted(target_directory.rglob("*"))
            if path.is_file()
        )
        if not preserved:
            target_directory.rmdir()
        self.manifest_path.unlink()
        with suppress(OSError):
            self.state_directory.rmdir()
        return ProbeInstallResult(
            operation="uninstall",
            changed=True,
            game_root=manifest.game_root,
            affected_files=(str(target.relative_to(manifest.game_root)),),
            preserved_files=preserved,
            completed_at=datetime.now(UTC),
            message="removed the unchanged owned probe and preserved unrecognized files",
        )

    def _require_installable(self, discovered: object) -> None:
        from sim_pilot.software_inc.discovery.models import SoftwareIncDiscoveryResult

        if not isinstance(discovered, SoftwareIncDiscoveryResult):
            raise SoftwareIncCompatibilityError("discovery returned an unexpected result")
        if not discovered.installed:
            raise SoftwareIncCompatibilityError("Software Inc. is not installed")
        if discovered.running:
            raise SoftwareIncProbeInstallError(
                "Software Inc. is running; close it before changing probe files"
            )
        if not discovered.compatible:
            detail = "; ".join(discovered.reasons) or "installation is incompatible"
            raise SoftwareIncCompatibilityError(detail)
        if discovered.game_root is None or discovered.mod_root is None:
            raise SoftwareIncCompatibilityError("official mod root was not discovered")

    @staticmethod
    def _safe_target_directory(game_root: Path, mod_root: Path) -> Path:
        if game_root.is_symlink() or mod_root.is_symlink():
            raise SoftwareIncProbeInstallError("game or mod root is a symlink")
        resolved_game = game_root.resolve(strict=True)
        if mod_root.exists():
            resolved_mod = mod_root.resolve(strict=True)
            if resolved_mod.parent != resolved_game:
                raise SoftwareIncProbeInstallError("DLLMods escapes the game root")
        elif mod_root.parent.resolve(strict=True) != resolved_game:
            raise SoftwareIncProbeInstallError("DLLMods parent is not the game root")
        target = mod_root / PROBE_DIRECTORY_NAME
        if target.is_symlink():
            raise SoftwareIncProbeInstallError("probe target is a symlink")
        return target

    def _load_manifest(self, *, required: bool) -> ProbeInstallManifest | None:
        if not self.manifest_path.is_file():
            if required:
                raise SoftwareIncProbeInstallError("no probe ownership manifest exists")
            return None
        if self.manifest_path.is_symlink():
            raise SoftwareIncProbeInstallError("probe ownership manifest is a symlink")
        if stat.S_IMODE(self.manifest_path.stat().st_mode) & 0o077:
            raise SoftwareIncProbeInstallError("probe ownership manifest is not owner-only")
        try:
            return ProbeInstallManifest.model_validate_json(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except Exception as error:
            raise SoftwareIncProbeInstallError("probe ownership manifest is invalid") from error

    def _required_manifest(self) -> ProbeInstallManifest:
        manifest = self._load_manifest(required=True)
        if manifest is None:
            raise SoftwareIncProbeInstallError("no probe ownership manifest exists")
        return manifest

    def _write_manifest(self, manifest: ProbeInstallManifest) -> None:
        if self.state_directory.is_symlink():
            raise SoftwareIncProbeInstallError("probe state directory is a symlink")
        self.state_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = self.state_directory / f".{self.manifest_path.name}.{uuid4().hex}.tmp"
        try:
            temporary.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _verify_owned_file(manifest: ProbeInstallManifest, *, allow_disabled: bool) -> None:
        if len(manifest.files) != 1:
            raise SoftwareIncProbeInstallError("probe manifest must own exactly one file")
        expected_relative = f"{PROBE_DIRECTORY_NAME}/{PROBE_SOURCE_NAME}"
        if manifest.files[0].relative_path != expected_relative:
            raise SoftwareIncProbeInstallError("probe manifest contains an unexpected owned path")
        if manifest.files[0].sha256 != manifest.source_sha256:
            raise SoftwareIncProbeInstallError("probe manifest source hashes disagree")
        source = manifest.mod_root / PROBE_DIRECTORY_NAME / PROBE_SOURCE_NAME
        disabled = manifest.mod_root / PROBE_DIRECTORY_NAME / PROBE_DISABLED_NAME
        target = source
        if allow_disabled and not source.exists():
            target = disabled
        if target.is_symlink() or not target.is_file():
            raise SoftwareIncProbeInstallError("manifest-owned probe file is missing")
        if _sha256(target) != manifest.files[0].sha256:
            raise SoftwareIncProbeInstallError(
                "manifest-owned probe file changed; refusing destructive operation"
            )

    def _verify_manifest_identity(self, manifest: ProbeInstallManifest, discovered: object) -> None:
        from sim_pilot.software_inc.discovery.models import SoftwareIncDiscoveryResult

        if not isinstance(discovered, SoftwareIncDiscoveryResult):
            raise SoftwareIncProbeInstallError("discovery returned an unexpected result")
        if discovered.game_root is None or discovered.mod_root is None:
            raise SoftwareIncProbeInstallError("current Software Inc. installation is unavailable")
        if manifest.game_root != discovered.game_root.resolve():
            raise SoftwareIncProbeInstallError("probe manifest belongs to another game root")
        if manifest.mod_root != discovered.mod_root.resolve():
            raise SoftwareIncProbeInstallError(
                "probe manifest belongs to another official mod root"
            )
        if manifest.steam_build_id != discovered.steam_build_id:
            raise SoftwareIncProbeInstallError("Steam build changed after probe installation")
        current_fingerprints = {item.name: item.sha256 for item in discovered.assembly_fingerprints}
        if manifest.assembly_fingerprints != current_fingerprints:
            raise SoftwareIncProbeInstallError(
                "managed assemblies changed after probe installation"
            )
        if not self.source_artifact.is_file():
            raise SoftwareIncProbeInstallError("official probe source artifact is missing")
        if manifest.source_artifact != self.source_artifact.resolve():
            raise SoftwareIncProbeInstallError("probe manifest references another source artifact")
        if manifest.source_sha256 != _sha256(self.source_artifact):
            raise SoftwareIncProbeInstallError("official probe source changed after installation")

    @staticmethod
    def _lifecycle_evidence() -> tuple[tuple[str, ...], tuple[int, ...]]:
        evidence: list[tuple[str, int]] = []
        log = current_player_log()
        if log is None:
            return (), ()
        try:
            for match in _LIFECYCLE.finditer(log.read_text(encoding="utf-8", errors="replace")):
                item = (match.group("event"), int(match.group("thread")))
                if item not in evidence:
                    evidence.append(item)
        except OSError:
            return (), ()
        return tuple(item[0] for item in evidence), tuple(item[1] for item in evidence)
