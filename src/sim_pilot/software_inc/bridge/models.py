"""Typed lifecycle and non-mutation evidence for the Software Inc. bridge."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from sim_pilot.software_inc.discovery.models import SoftwareIncDiscoveryResult


class BridgeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class BridgeOwnedFile(BridgeModel):
    relative_path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BridgeInstallManifest(BridgeModel):
    schema_version: Literal[1] = 1
    game_root: Path
    mod_root: Path
    artifact: Path
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    product_version: str | None
    steam_build_id: str
    assembly_fingerprints: dict[str, str]
    installed_at: AwareDatetime
    files: tuple[BridgeOwnedFile, ...]


class SoftwareIncBridgeReport(BridgeModel):
    schema_version: Literal[1] = 1
    discovery: SoftwareIncDiscoveryResult
    artifact: Path
    artifact_available: bool
    artifact_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    installed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    artifact_matches_installed: bool | None = None
    manifest_path: Path
    installed: bool
    enabled: bool
    loaded: bool
    broad_access_required: Literal[True] = True
    broad_access_scope: tuple[str, ...] = ("owner-only token read", "loopback networking")
    gameplay_actions: tuple[()] = ()
    reasons: tuple[str, ...] = ()


class BridgeInstallResult(BridgeModel):
    schema_version: Literal[1] = 1
    operation: Literal["install", "disable", "uninstall"]
    changed: bool
    game_root: Path
    affected_files: tuple[str, ...]
    preserved_files: tuple[str, ...] = ()
    completed_at: AwareDatetime
    message: str = Field(min_length=1)


class BridgeReadOnlyProof(BridgeModel):
    schema_version: Literal[1] = 1
    passed: bool
    bridge_instance_id: str
    game_session_id: str
    paused: bool
    gameplay_actions: tuple[str, ...] = ()
    observed_surfaces: tuple[str, ...]
    semantic_fingerprint_before: str = Field(pattern=r"^[0-9a-f]{64}$")
    semantic_fingerprint_after: str = Field(pattern=r"^[0-9a-f]{64}$")
    save_file_count: int = Field(ge=0)
    save_fingerprint_before: str = Field(pattern=r"^[0-9a-f]{64}$")
    save_fingerprint_after: str = Field(pattern=r"^[0-9a-f]{64}$")
    completed_at: datetime
    reasons: tuple[str, ...]
