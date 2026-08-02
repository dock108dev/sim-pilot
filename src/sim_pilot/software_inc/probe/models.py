"""Strict ownership and lifecycle records for the Software Inc. probe."""

from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sim_pilot.software_inc.discovery.models import SoftwareIncDiscoveryResult


class ProbeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ProbeOwnedFile(ProbeModel):
    schema_version: Literal[1] = 1
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProbeInstallManifest(ProbeModel):
    schema_version: Literal[1] = 1
    game_root: Path
    mod_root: Path
    source_artifact: Path
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_version: str | None = None
    steam_build_id: str | None = None
    assembly_fingerprints: dict[str, str]
    installed_at: AwareDatetime
    files: tuple[ProbeOwnedFile, ...]


class SoftwareIncProbeReport(ProbeModel):
    schema_version: Literal[1] = 1
    discovery: SoftwareIncDiscoveryResult
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    manifest_path: Path
    manifest_valid: bool
    installed: bool
    enabled: bool
    loaded: bool
    lifecycle_events: tuple[str, ...] = ()
    lifecycle_thread_ids: tuple[int, ...] = ()
    broad_access_requested: bool
    save_serialization_declared: bool
    reasons: tuple[str, ...] = ()


class ProbeInstallResult(ProbeModel):
    schema_version: Literal[1] = 1
    operation: Literal["install", "disable", "uninstall"]
    changed: bool
    game_root: Path
    affected_files: tuple[str, ...]
    preserved_files: tuple[str, ...] = ()
    completed_at: AwareDatetime
    message: str = Field(min_length=1)
