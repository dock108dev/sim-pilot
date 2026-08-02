"""Strict Software Inc. installation, runtime, and permission evidence."""

from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DiscoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class DiscoveryStatus(StrEnum):
    OBSERVED = "observed"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


class Distribution(StrEnum):
    STEAM = "steam"
    DRM_FREE = "drm_free"
    UNKNOWN = "unknown"


class ScriptingBackend(StrEnum):
    MONO = "mono"
    IL2CPP = "il2cpp"
    UNKNOWN = "unknown"


class DiscoveryCoverage(DiscoveryModel):
    schema_version: Literal[1] = 1
    surface: str = Field(min_length=1)
    status: DiscoveryStatus
    detail: str = Field(min_length=1)


class AssemblyFingerprint(DiscoveryModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    path: Path
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class SoftwareIncWindowIdentity(DiscoveryModel):
    schema_version: Literal[1] = 1
    process_id: int = Field(ge=1)
    title: str = Field(min_length=1)
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    display_scale: float = Field(gt=0, le=4)


class SoftwareIncDiscoveryResult(DiscoveryModel):
    schema_version: Literal[1] = 1
    steam_app_id: Literal["362620"] = "362620"
    distribution: Distribution
    installed: bool
    game_root: Path | None = None
    app_path: Path | None = None
    executable_path: Path | None = None
    bundle_version: str | None = None
    product_version: str | None = None
    steam_build_id: str | None = None
    executable_architectures: tuple[str, ...] = ()
    running_architecture: str | None = None
    unity_version: str | None = None
    scripting_backend: ScriptingBackend = ScriptingBackend.UNKNOWN
    managed_directory: Path | None = None
    assembly_fingerprints: tuple[AssemblyFingerprint, ...] = ()
    official_code_mod_api_observed: bool = False
    mod_root: Path | None = None
    save_path_candidates: tuple[Path, ...] = ()
    discovered_save_paths: tuple[Path, ...] = ()
    running: bool = False
    process_id: int | None = Field(default=None, ge=1)
    process_parentage: str | None = None
    window: SoftwareIncWindowIdentity | None = None
    accessibility_trusted: bool | None = None
    screen_capture_functional: bool | None = None
    probe_source_available: bool
    probe_installed: bool
    probe_enabled: bool
    probe_loaded: bool
    compatible: bool
    live_supported: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    coverage: tuple[DiscoveryCoverage, ...]
