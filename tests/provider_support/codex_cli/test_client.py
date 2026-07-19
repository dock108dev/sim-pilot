"""Command, isolation, structured-output, and failure contracts."""

import asyncio
import json
import shutil
import stat
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from sim_pilot.provider_support.codex_cli.client import AsyncioProcessRunner, CodexCLIClient
from sim_pilot.provider_support.codex_cli.errors import (
    CodexCLIAuthenticationExpiredError,
    CodexCLIInvalidStructuredOutputError,
    CodexCLIMalformedJSONLError,
    CodexCLIMissingFinalResponseError,
    CodexCLIOutputLimitError,
    CodexCLIProcessStartError,
    CodexCLIRefusalError,
    CodexCLISandboxError,
    CodexCLITemporaryDirectoryError,
    CodexCLITimeoutError,
    CodexCLIUsageLimitError,
)
from tests.provider_support.codex_cli.helpers import FakeProcessRunner, capabilities


class ExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: str


def test_client_builds_isolated_non_shell_command_and_cleans_directory(tmp_path: Path) -> None:
    runner = FakeProcessRunner('{"value":"ok"}')
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )

    output, metadata, events = asyncio.run(
        client.execute(prompt="bounded prompt", output_type=ExampleOutput, prompt_version="v1")
    )

    assert output == ExampleOutput(value="ok")
    assert metadata.provider == "codex"
    assert metadata.provider_version == "codex-cli 0.141.0"
    assert metadata.request_id == "thread_test"
    assert metadata.started_at is not None
    assert metadata.completed_at is not None
    assert metadata.subprocess_exit_code == 0
    assert metadata.token_usage is not None
    assert metadata.token_usage.cached_input_tokens == 25
    assert events.unknown_event_types == ("future.telemetry",)
    command = runner.commands[0]
    assert command[:2] == ("/fake/codex", "exec")
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "--ephemeral" in command
    assert "--json" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert command[command.index("-c") + 1] == 'approval_policy="never"'
    assert command[command.index("--model") + 1] == "gpt-5.6"
    assert "--add-dir" not in command
    assert (
        runner.environments[0]
        .keys()
        .isdisjoint({"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"})
    )
    assert not runner.working_directories[0].exists()


def test_client_preserves_owner_only_debug_directory_when_explicit(tmp_path: Path) -> None:
    runner = FakeProcessRunner('{"value":"ok"}')
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        preserve_debug_directory=True,
        runner=runner,
        capabilities=capabilities(),
    )
    asyncio.run(client.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1"))

    directory = runner.working_directories[0]
    assert directory.exists()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert set(path.name for path in directory.iterdir()) == {
        "output-schema.json",
        "structured-output.json",
    }
    assert stat.S_IMODE((directory / "output-schema.json").stat().st_mode) == 0o600
    shutil.rmtree(directory)


def test_client_rejects_temporary_directory_inside_repository() -> None:
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=Path.cwd(),
        runner=FakeProcessRunner('{"value":"ok"}'),
        capabilities=capabilities(),
    )

    with pytest.raises(CodexCLITemporaryDirectoryError, match="inside a Git repository"):
        asyncio.run(client.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1"))


def test_client_rejects_missing_and_invalid_structured_output(tmp_path: Path) -> None:
    missing = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=FakeProcessRunner("{}", write_output=False),
        capabilities=capabilities(),
    )
    with pytest.raises(CodexCLIMissingFinalResponseError):
        asyncio.run(
            missing.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1")
        )

    invalid = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=FakeProcessRunner('{"wrong":true}'),
        capabilities=capabilities(),
    )
    with pytest.raises(CodexCLIInvalidStructuredOutputError):
        asyncio.run(
            invalid.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1")
        )


@pytest.mark.parametrize(
    ("stderr", "error_type"),
    [
        (b"usage limit reached", CodexCLIUsageLimitError),
        (b"authentication expired", CodexCLIAuthenticationExpiredError),
        (b"sandbox initialization failed", CodexCLISandboxError),
        (b"model refused the request", CodexCLIRefusalError),
    ],
)
def test_client_classifies_nonzero_exit(
    tmp_path: Path, stderr: bytes, error_type: type[Exception]
) -> None:
    runner = FakeProcessRunner('{"value":"ok"}', exit_code=1, stderr=stderr)
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    with pytest.raises(error_type):
        asyncio.run(client.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1"))


def test_canonical_schemas_are_closed_and_serializable() -> None:
    schema = ExampleOutput.model_json_schema()
    assert schema["additionalProperties"] is False
    assert json.loads(json.dumps(schema)) == schema


def test_client_rejects_malformed_jsonl_and_cleans_failed_directory(tmp_path: Path) -> None:
    runner = FakeProcessRunner('{"value":"ok"}', stdout=b"not-json\n")
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    with pytest.raises(CodexCLIMalformedJSONLError):
        asyncio.run(client.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1"))
    assert not runner.working_directories[0].exists()


def test_raw_event_debug_mode_is_explicit_sanitized_and_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SIM_PILOT_CODEX_RECORD_RAW_EVENTS", "1")
    runner = FakeProcessRunner('{"value":"ok"}')
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    _, metadata, _ = asyncio.run(
        client.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1")
    )

    directory = runner.working_directories[0]
    raw_path = directory / "codex-events.jsonl"
    assert raw_path.is_file()
    assert stat.S_IMODE(raw_path.stat().st_mode) == 0o600
    assert "future.telemetry" not in raw_path.read_text()
    assert "sanitized_raw_events_preserved" in metadata.telemetry_notes
    shutil.rmtree(directory)


def test_async_process_runner_enforces_timeout_and_output_bounds(tmp_path: Path) -> None:
    runner = AsyncioProcessRunner()
    environment = {"PATH": str(Path(sys.executable).parent)}
    with pytest.raises(CodexCLIOutputLimitError):
        asyncio.run(
            runner.run(
                (sys.executable, "-c", "print('x' * 1000)"),
                cwd=tmp_path,
                environment=environment,
                timeout_seconds=2,
                maximum_stdout_bytes=10,
                maximum_stderr_bytes=100,
            )
        )
    with pytest.raises(CodexCLIOutputLimitError):
        asyncio.run(
            runner.run(
                (sys.executable, "-c", "import sys; sys.stderr.write('x' * 1000)"),
                cwd=tmp_path,
                environment=environment,
                timeout_seconds=2,
                maximum_stdout_bytes=100,
                maximum_stderr_bytes=10,
            )
        )
    with pytest.raises(CodexCLITimeoutError):
        asyncio.run(
            runner.run(
                (sys.executable, "-c", "import time; time.sleep(5)"),
                cwd=tmp_path,
                environment=environment,
                timeout_seconds=0.01,
                maximum_stdout_bytes=100,
                maximum_stderr_bytes=100,
            )
        )

    with pytest.raises(CodexCLIProcessStartError):
        asyncio.run(
            runner.run(
                ("/definitely/missing/codex",),
                cwd=tmp_path,
                environment=environment,
                timeout_seconds=1,
                maximum_stdout_bytes=100,
                maximum_stderr_bytes=100,
            )
        )
