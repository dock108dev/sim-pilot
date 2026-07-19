"""Command, isolation, structured-output, and failure contracts."""

import asyncio
import json
import logging
import shutil
import stat
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from sim_pilot.domain.models import JsonValue
from sim_pilot.intent_compiler import CompilerResponse
from sim_pilot.provider_support.codex_cli.client import (
    AsyncioProcessRunner,
    CodexCLIClient,
    codex_output_schema,
)
from sim_pilot.provider_support.codex_cli.errors import (
    CodexCLIAuthenticationExpiredError,
    CodexCLIInvalidStructuredOutputError,
    CodexCLIMalformedJSONLError,
    CodexCLIMissingFinalResponseError,
    CodexCLINonzeroExitError,
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
    assert metadata.request_id == "thread_test_1"
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
    assert command[command.index("--disable") + 1] == "shell_tool"
    assert command[command.index("-c") + 1] == 'approval_policy="never"'
    assert command[command.index("--model") + 1] == "gpt-5.6"
    assert "--add-dir" not in command
    assert command[-1] == "-"
    assert runner.stdin == [b"bounded prompt"]
    assert (
        runner.environments[0]
        .keys()
        .isdisjoint({"OPENAI_API_KEY", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN"})
    )
    assert not runner.working_directories[0].exists()


def test_client_transports_and_validates_canonical_json_payload(tmp_path: Path) -> None:
    runner = FakeProcessRunner('{"payload":"{\\"value\\":\\"ok\\"}"}')
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )

    output, _, _ = asyncio.run(
        client.execute_canonical(
            prompt="bounded prompt",
            output_type=ExampleOutput,
            prompt_version="v1",
        )
    )

    assert output == ExampleOutput(value="ok")
    transported_prompt = runner.stdin[0].decode()
    assert "one field named payload" in transported_prompt
    assert '"properties":{"value"' in transported_prompt


def test_client_rejects_invalid_canonical_json_payload(tmp_path: Path) -> None:
    runner = FakeProcessRunner('{"payload":"{\\"wrong\\":true}"}')
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )

    with pytest.raises(
        CodexCLIInvalidStructuredOutputError,
        match="canonical payload failed schema validation: .*value: missing",
    ):
        asyncio.run(
            client.execute_canonical(
                prompt="bounded prompt",
                output_type=ExampleOutput,
                prompt_version="v1",
            )
        )


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
        "codex-diagnostics.json",
        "output-schema.json",
        "structured-output.json",
    }
    assert stat.S_IMODE((directory / "output-schema.json").stat().st_mode) == 0o600
    diagnostics_path = directory / "codex-diagnostics.json"
    assert stat.S_IMODE(diagnostics_path.stat().st_mode) == 0o600
    diagnostics = json.loads(diagnostics_path.read_text())
    assert diagnostics["codex_version"] == "codex-cli 0.141.0"
    assert diagnostics["request_id"] == "thread_test_1"
    assert diagnostics["parser_state"] == "parsed"
    assert diagnostics["termination_reason"] == "completed"
    assert diagnostics["command"][-1] == "-"
    assert "bounded prompt" not in diagnostics_path.read_text()
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


def test_codex_schema_requires_every_declared_property_recursively() -> None:
    schema = codex_output_schema(CompilerResponse)

    def assert_required(value: JsonValue) -> None:
        if isinstance(value, list):
            for item in value:
                assert_required(item)
            return
        if not isinstance(value, dict):
            return
        properties = value.get("properties")
        if value.get("type") == "object" and isinstance(properties, dict):
            assert value.get("required") == list(properties)
        for item in value.values():
            assert_required(item)

    assert_required(schema)


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


def test_cleanup_failure_does_not_mask_primary_provider_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = FakeProcessRunner('{"value":"ok"}', stdout=b"not-json\n")
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    real_rmtree = shutil.rmtree

    def fail_cleanup(path: Path) -> None:
        del path
        raise OSError("cleanup unavailable")

    with monkeypatch.context() as scoped:
        scoped.setattr(shutil, "rmtree", fail_cleanup)
        with (
            caplog.at_level(logging.ERROR, logger="sim_pilot.provider_support.codex_cli.client"),
            pytest.raises(CodexCLIMalformedJSONLError) as caught,
        ):
            asyncio.run(
                client.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1")
            )

    assert any("cleanup also failed" in note for note in caught.value.__notes__)
    assert "cleanup failed while another error was active" in caplog.text
    real_rmtree(runner.working_directories[0])


def test_failed_parser_state_cannot_leak_into_next_invocation(tmp_path: Path) -> None:
    runner = FakeProcessRunner('{"value":"ok"}', stdout=b'{"type":')
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    with pytest.raises(CodexCLIMalformedJSONLError):
        asyncio.run(client.execute(prompt="first", output_type=ExampleOutput, prompt_version="v1"))

    runner.stdout = None
    output, metadata, _ = asyncio.run(
        client.execute(prompt="second", output_type=ExampleOutput, prompt_version="v1")
    )
    assert output.value == "ok"
    assert metadata.request_id == "thread_test_2"
    assert runner.stdin == [b"first", b"second"]


def test_nonzero_exit_reports_jsonl_error_not_informational_stdin_message(
    tmp_path: Path,
) -> None:
    stdout = (
        b'{"type":"thread.started","thread_id":"failed_request"}\n'
        b'{"type":"turn.failed","error":"actual provider failure"}\n'
    )
    runner = FakeProcessRunner(
        '{"value":"stale"}',
        exit_code=1,
        stdout=stdout,
        stderr=b"Reading additional input from stdin...\n",
    )
    client = CodexCLIClient(
        model="gpt-5.6",
        temporary_directory_root=tmp_path,
        runner=runner,
        capabilities=capabilities(),
    )
    with pytest.raises(CodexCLINonzeroExitError, match="actual provider failure") as caught:
        asyncio.run(client.execute(prompt="prompt", output_type=ExampleOutput, prompt_version="v1"))
    assert "additional input" not in str(caught.value)


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
                stdin=b"",
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
                stdin=b"",
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
                stdin=b"",
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
                stdin=b"",
                cwd=tmp_path,
                environment=environment,
                timeout_seconds=1,
                maximum_stdout_bytes=100,
                maximum_stderr_bytes=100,
            )
        )
