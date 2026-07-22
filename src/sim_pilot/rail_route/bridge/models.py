"""Strict models for loader compatibility and reversible installation state."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class BridgeCompatibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    compatible: bool
    game_root: Path
    app_path: Path
    game_version: str
    steam_build_id: str | None
    unity_version: str
    scripting_backend: Literal["mono", "unknown"]
    executable_architectures: tuple[str, ...]
    loader_version: str
    loader_architectures: tuple[str, ...]
    plugin_artifact: Path
    plugin_available: bool
    installed: bool
    enabled: bool
    reasons: tuple[str, ...]


class InstalledFileRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    relative_path: str
    sha256: str


class BridgeInstallManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    game_root: Path
    app_path: Path
    game_version: str
    steam_build_id: str
    loader_version: str
    loader_archive_sha256: str
    plugin_sha256: str
    files: tuple[InstalledFileRecord, ...]


class BridgeInstallResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    operation: Literal["install", "disable", "uninstall"]
    changed: bool
    game_root: Path
    affected_files: tuple[str, ...]
    message: str


class BridgeReadOnlyProof(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

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
    reasons: tuple[str, ...]
