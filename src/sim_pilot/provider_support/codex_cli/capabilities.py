"""Non-billable capability discovery for the locally installed Codex CLI."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sim_pilot.provider_support.codex_cli.errors import (
    CodexCLICompatibilityError,
    CodexCLIExecutableNotFoundError,
    CodexCLIUnauthenticatedError,
)


class CodexCLICapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    executable_path: Path
    version: str
    authenticated: bool
    authentication_method: str | None = None
    supports_exec: bool
    supports_ephemeral: bool
    supports_jsonl: bool
    supports_output_schema: bool
    supports_output_last_message: bool
    supports_read_only_sandbox: bool
    supports_model_selection: bool
    supports_working_directory: bool
    supports_ignore_user_config: bool
    supports_ignore_rules: bool
    supports_skip_git_repo_check: bool
    supports_feature_disable: bool
    approval_configuration: Literal["config_override"] | None = None

    def require_provider_contract(self) -> None:
        required = {
            "codex exec": self.supports_exec,
            "--ephemeral": self.supports_ephemeral,
            "--json": self.supports_jsonl,
            "--output-schema": self.supports_output_schema,
            "--output-last-message": self.supports_output_last_message,
            "--sandbox read-only": self.supports_read_only_sandbox,
            "--model": self.supports_model_selection,
            "--cd": self.supports_working_directory,
            "--ignore-user-config": self.supports_ignore_user_config,
            "--ignore-rules": self.supports_ignore_rules,
            "--skip-git-repo-check": self.supports_skip_git_repo_check,
            "--disable shell_tool": self.supports_feature_disable,
            "approval_policy config override": self.approval_configuration is not None,
        }
        missing = tuple(name for name, available in required.items() if not available)
        if missing:
            raise CodexCLICompatibilityError(
                "installed Codex CLI is missing required features: "
                f"{', '.join(missing)}; upgrade Codex CLI before selecting provider codex"
            )
        if not self.authenticated:
            raise CodexCLIUnauthenticatedError(
                "Codex CLI is not authenticated; run `codex login` before selecting provider codex"
            )


CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]
_CACHE: dict[str, tuple[float, CodexCLICapabilities]] = {}


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - fixed argument list, no shell
        tuple(command),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def probe_codex_cli(
    executable: Path | None = None,
    *,
    runner: CommandRunner = _run,
    cache_duration_seconds: float = 60.0,
) -> CodexCLICapabilities:
    """Inspect version, help, and login state without a model request."""
    located = str(executable) if executable is not None else shutil.which("codex")
    if not located:
        raise CodexCLIExecutableNotFoundError(
            "Codex CLI executable not found; install Codex CLI or configure "
            "SIM_PILOT_CODEX_EXECUTABLE"
        )
    path = Path(located).expanduser().resolve()
    if runner is _run and (not path.is_file() or not os.access(path, os.X_OK)):
        raise CodexCLIExecutableNotFoundError(
            f"configured Codex CLI executable is missing or not executable: {path}"
        )
    cache_key = str(path)
    cached = _CACHE.get(cache_key)
    if cached is not None and monotonic() - cached[0] < cache_duration_seconds:
        return cached[1]
    try:
        version_result = runner((str(path), "--version"))
        help_result = runner((str(path), "exec", "--help"))
        login_result = runner((str(path), "login", "status"))
    except (OSError, subprocess.SubprocessError) as error:
        raise CodexCLICompatibilityError(f"Codex CLI capability probe failed: {error}") from error
    version = (version_result.stdout or version_result.stderr).strip()
    help_text = f"{help_result.stdout}\n{help_result.stderr}"
    login_text = f"{login_result.stdout}\n{login_result.stderr}".strip()
    if version_result.returncode != 0 or not version:
        raise CodexCLICompatibilityError(
            "Codex CLI version probe failed; reinstall or upgrade Codex CLI"
        )
    capabilities = CodexCLICapabilities(
        executable_path=path,
        version=version,
        authenticated=login_result.returncode == 0 and "logged in" in login_text.lower(),
        authentication_method=(login_text if login_result.returncode == 0 else None),
        supports_exec=help_result.returncode == 0 and "Run Codex non-interactively" in help_text,
        supports_ephemeral="--ephemeral" in help_text,
        supports_jsonl="--json" in help_text,
        supports_output_schema="--output-schema" in help_text,
        supports_output_last_message="--output-last-message" in help_text,
        supports_read_only_sandbox="--sandbox" in help_text and "read-only" in help_text,
        supports_model_selection="--model" in help_text,
        supports_working_directory="--cd" in help_text,
        supports_ignore_user_config="--ignore-user-config" in help_text,
        supports_ignore_rules="--ignore-rules" in help_text,
        supports_skip_git_repo_check="--skip-git-repo-check" in help_text,
        supports_feature_disable="--disable" in help_text,
        approval_configuration=("config_override" if "--config" in help_text else None),
    )
    _CACHE[cache_key] = (monotonic(), capabilities)
    return capabilities
