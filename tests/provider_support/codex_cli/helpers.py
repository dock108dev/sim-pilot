"""Deterministic fake Codex process transport."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from sim_pilot.provider_support.codex_cli.capabilities import CodexCLICapabilities
from sim_pilot.provider_support.codex_cli.client import ProcessResult


def capabilities(*, authenticated: bool = True) -> CodexCLICapabilities:
    return CodexCLICapabilities(
        executable_path=Path("/fake/codex"),
        version="codex-cli 0.141.0",
        authenticated=authenticated,
        authentication_method="Logged in using ChatGPT" if authenticated else None,
        supports_exec=True,
        supports_ephemeral=True,
        supports_jsonl=True,
        supports_output_schema=True,
        supports_output_last_message=True,
        supports_read_only_sandbox=True,
        supports_model_selection=True,
        supports_working_directory=True,
        supports_ignore_user_config=True,
        supports_ignore_rules=True,
        supports_skip_git_repo_check=True,
        approval_configuration="config_override",
    )


class FakeProcessRunner:
    def __init__(
        self,
        output: str,
        *,
        exit_code: int = 0,
        stdout: bytes | None = None,
        stderr: bytes = b"",
        write_output: bool = True,
    ) -> None:
        self.output = output
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.write_output = write_output
        self.commands: list[tuple[str, ...]] = []
        self.working_directories: list[Path] = []
        self.environments: list[dict[str, str]] = []

    async def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_stdout_bytes: int,
        maximum_stderr_bytes: int,
    ) -> ProcessResult:
        del timeout_seconds, maximum_stdout_bytes, maximum_stderr_bytes
        materialized = tuple(command)
        self.commands.append(materialized)
        self.working_directories.append(cwd)
        self.environments.append(dict(environment))
        if self.write_output:
            output_path = Path(materialized[materialized.index("--output-last-message") + 1])
            output_path.write_text(self.output, encoding="utf-8")
            output_path.chmod(0o600)
        stdout = self.stdout
        if stdout is None:
            events = (
                {"type": "thread.started", "thread_id": "thread_test"},
                {"type": "turn.started"},
                {"type": "future.telemetry", "safe": True},
                {
                    "type": "item.completed",
                    "item": {"id": "item_1", "type": "agent_message", "text": self.output},
                },
                {
                    "type": "turn.completed",
                    "usage": {
                        "input_tokens": 100,
                        "cached_input_tokens": 25,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 5,
                    },
                },
            )
            stdout = ("\n".join(json.dumps(event) for event in events) + "\n").encode()
        return ProcessResult(self.exit_code, stdout, self.stderr)
