"""Capability probing without model execution."""

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from sim_pilot.provider_support.codex_cli.capabilities import probe_codex_cli
from sim_pilot.provider_support.codex_cli.errors import (
    CodexCLICompatibilityError,
    CodexCLIExecutableNotFoundError,
    CodexCLIUnauthenticatedError,
)


def _runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    if "--version" in command:
        return subprocess.CompletedProcess(command, 0, "codex-cli 0.141.0\n", "")
    if "--help" in command:
        help_text = """Run Codex non-interactively
--ephemeral --json --output-schema --output-last-message --sandbox read-only --model --cd
--ignore-user-config --ignore-rules --skip-git-repo-check --config
"""
        return subprocess.CompletedProcess(command, 0, help_text, "")
    return subprocess.CompletedProcess(command, 0, "Logged in using ChatGPT\n", "")


def test_capability_probe_uses_only_version_help_and_login_status() -> None:
    commands: list[tuple[str, ...]] = []

    def runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        commands.append(tuple(command))
        return _runner(command)

    result = probe_codex_cli(Path("/fake/codex"), runner=runner, cache_duration_seconds=0)

    assert result.version == "codex-cli 0.141.0"
    assert result.authenticated is True
    result.require_provider_contract()
    assert [command[1:] for command in commands] == [
        ("--version",),
        ("exec", "--help"),
        ("login", "status"),
    ]


def test_probe_rejects_missing_feature_and_unauthenticated_cli() -> None:
    def missing_json(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        result = _runner(command)
        return subprocess.CompletedProcess(
            command, result.returncode, result.stdout.replace("--json", ""), ""
        )

    capabilities = probe_codex_cli(
        Path("/fake/codex"), runner=missing_json, cache_duration_seconds=0
    )
    with pytest.raises(CodexCLICompatibilityError, match="--json"):
        capabilities.require_provider_contract()

    def logged_out(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        if command[-2:] == ("login", "status"):
            return subprocess.CompletedProcess(command, 1, "", "Not logged in")
        return _runner(command)

    capabilities = probe_codex_cli(Path("/fake/codex"), runner=logged_out, cache_duration_seconds=0)
    with pytest.raises(CodexCLIUnauthenticatedError, match="codex login"):
        capabilities.require_provider_contract()


def test_probe_reports_missing_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_which(name: str) -> None:
        del name
        return None

    monkeypatch.setattr("shutil.which", missing_which)
    with pytest.raises(CodexCLIExecutableNotFoundError, match="executable not found"):
        probe_codex_cli(cache_duration_seconds=0)

    with pytest.raises(CodexCLIExecutableNotFoundError, match="missing or not executable"):
        probe_codex_cli(Path("/definitely/missing/codex"), cache_duration_seconds=0)
