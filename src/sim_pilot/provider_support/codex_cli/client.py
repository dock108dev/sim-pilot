"""Isolated, bounded, structured execution through authenticated `codex exec`."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Literal, Protocol, TypeVar, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from sim_pilot.domain.models import JsonValue
from sim_pilot.provider_metadata import ProviderMetadata
from sim_pilot.provider_support.codex_cli.capabilities import CodexCLICapabilities, probe_codex_cli
from sim_pilot.provider_support.codex_cli.errors import (
    CodexCLIAuthenticationExpiredError,
    CodexCLIConflictingFinalResponseError,
    CodexCLIInvalidStructuredOutputError,
    CodexCLIMissingFinalResponseError,
    CodexCLINonzeroExitError,
    CodexCLIOutputLimitError,
    CodexCLIProcessStartError,
    CodexCLIProcessTerminationError,
    CodexCLIRefusalError,
    CodexCLISandboxError,
    CodexCLISchemaFileError,
    CodexCLITemporaryDirectoryError,
    CodexCLITimeoutError,
    CodexCLIUsageLimitError,
)
from sim_pilot.provider_support.codex_cli.events import ParsedCodexEvents, parse_codex_jsonl

OutputT = TypeVar("OutputT", bound=BaseModel)
JSON_OBJECT_ADAPTER = TypeAdapter(dict[str, object])


def codex_output_schema(output_type: type[BaseModel]) -> dict[str, JsonValue]:
    """Make Pydantic's schema explicit enough for Codex strict structured output."""

    def normalize(value: JsonValue) -> JsonValue:
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if not isinstance(value, dict):
            return value
        normalized: dict[str, JsonValue] = {
            str(key): normalize(item) for key, item in value.items()
        }
        properties = normalized.get("properties")
        if normalized.get("type") == "object" and isinstance(properties, dict):
            normalized["required"] = list(properties)
        return normalized

    schema = cast("JsonValue", output_type.model_json_schema())
    normalized = normalize(schema)
    if not isinstance(normalized, dict):
        raise CodexCLISchemaFileError("Codex output schema root must be an object")
    return normalized


class CodexCLIResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    output: dict[str, object]
    metadata: ProviderMetadata
    exit_code: int
    unknown_event_types: tuple[str, ...] = ()
    debug_directory: Path | None = None


class CodexCanonicalEnvelope(BaseModel):
    """Strict transport for canonical models containing arbitrary JSON maps."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    payload: str = Field(min_length=2)


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    process_id: int | None = None


class ProcessRunner(Protocol):
    async def run(
        self,
        command: Sequence[str],
        *,
        stdin: bytes,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_stdout_bytes: int,
        maximum_stderr_bytes: int,
    ) -> ProcessResult: ...


class AsyncioProcessRunner:
    async def run(
        self,
        command: Sequence[str],
        *,
        stdin: bytes,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        maximum_stdout_bytes: int,
        maximum_stderr_bytes: int,
    ) -> ProcessResult:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=cwd,
                env=dict(environment),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise CodexCLIProcessStartError(f"could not start Codex CLI: {error}") from error
        if process.stdin is None or process.stdout is None or process.stderr is None:
            await self._terminate(process)
            raise CodexCLIProcessStartError("Codex CLI subprocess pipes were unavailable")
        process_stdin = process.stdin

        async def read_bounded(stream: asyncio.StreamReader, limit: int, label: str) -> bytes:
            chunks: list[bytes] = []
            length = 0
            while chunk := await stream.read(65_536):
                length += len(chunk)
                if length > limit:
                    raise CodexCLIOutputLimitError(f"Codex CLI {label} exceeded {limit} bytes")
                chunks.append(chunk)
            return b"".join(chunks)

        async def write_prompt() -> None:
            try:
                process_stdin.write(stdin)
                await process_stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                process_stdin.close()
                with suppress(BrokenPipeError, ConnectionResetError):
                    await process_stdin.wait_closed()

        tasks = (
            asyncio.create_task(process.wait()),
            asyncio.create_task(read_bounded(process.stdout, maximum_stdout_bytes, "stdout")),
            asyncio.create_task(read_bounded(process.stderr, maximum_stderr_bytes, "stderr")),
            asyncio.create_task(write_prompt()),
        )
        try:
            _, stdout, stderr, _ = await asyncio.wait_for(
                asyncio.gather(*tasks), timeout=timeout_seconds
            )
        except TimeoutError as error:
            for task in tasks:
                task.cancel()
            await self._terminate(process)
            timeout_error = CodexCLITimeoutError(
                f"Codex CLI exceeded the {timeout_seconds:g}-second timeout"
            )
            timeout_error.process_id = process.pid  # type: ignore[attr-defined]
            raise timeout_error from error
        except CodexCLIOutputLimitError:
            for task in tasks:
                task.cancel()
            await self._terminate(process)
            raise
        return ProcessResult(process.returncode or 0, stdout, stderr, process.pid)

    @staticmethod
    async def _terminate(process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=2)
        except (ProcessLookupError, TimeoutError):
            try:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=2)
            except (ProcessLookupError, TimeoutError) as error:
                raise CodexCLIProcessTerminationError(
                    "Codex CLI subprocess could not be terminated"
                ) from error


class CodexCLIClient:
    """Run one schema-bound provider request in a fresh empty directory."""

    def __init__(
        self,
        *,
        model: str,
        timeout_seconds: float = 120,
        executable: Path | None = None,
        temporary_directory_root: Path | None = None,
        preserve_debug_directory: bool = False,
        maximum_stdout_bytes: int = 2_000_000,
        maximum_stderr_bytes: int = 64_000,
        capability_cache_seconds: float = 60,
        runner: ProcessRunner | None = None,
        capabilities: CodexCLICapabilities | None = None,
    ) -> None:
        if not model.strip():
            raise ValueError("Codex CLI model must not be empty")
        if timeout_seconds <= 0 or maximum_stdout_bytes <= 0 or maximum_stderr_bytes <= 0:
            raise ValueError("Codex CLI timeout and output limits must be positive")
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._temporary_directory_root = temporary_directory_root
        self._record_raw_events = os.getenv("SIM_PILOT_CODEX_RECORD_RAW_EVENTS", "0") == "1"
        self._preserve_debug_directory = preserve_debug_directory or self._record_raw_events
        self._maximum_stdout_bytes = maximum_stdout_bytes
        self._maximum_stderr_bytes = maximum_stderr_bytes
        self._runner = runner or AsyncioProcessRunner()
        self._capabilities = capabilities or probe_codex_cli(
            executable, cache_duration_seconds=capability_cache_seconds
        )
        self._capabilities.require_provider_contract()

    @property
    def capabilities(self) -> CodexCLICapabilities:
        return self._capabilities

    async def execute(
        self,
        *,
        prompt: str,
        output_type: type[OutputT],
        prompt_version: str,
    ) -> tuple[OutputT, ProviderMetadata, ParsedCodexEvents]:
        if not prompt.strip():
            raise ValueError("Codex CLI prompt must not be empty")
        invocation_id = str(uuid4())
        directory = self._create_directory()
        schema_path = directory / "output-schema.json"
        output_path = directory / "structured-output.json"
        diagnostics: dict[str, object] = {
            "schema_version": 1,
            "invocation_id": invocation_id,
            "codex_version": self._capabilities.version,
            "temporary_directory": str(directory),
            "timeout_seconds": self._timeout_seconds,
            "parser_state": "not_started",
            "termination_reason": "not_started",
            "request_id": None,
            "process_id": None,
            "elapsed_ms": None,
        }
        try:
            self._write_schema(schema_path, output_type)
            command = self._command(directory, schema_path, output_path)
            diagnostics["command"] = list(command)
            started_at = datetime.now(UTC)
            started = perf_counter()
            try:
                result = await self._runner.run(
                    command,
                    stdin=prompt.encode("utf-8"),
                    cwd=directory,
                    environment=self._environment(),
                    timeout_seconds=self._timeout_seconds,
                    maximum_stdout_bytes=self._maximum_stdout_bytes,
                    maximum_stderr_bytes=self._maximum_stderr_bytes,
                )
            except Exception as error:
                diagnostics["elapsed_ms"] = (perf_counter() - started) * 1000
                diagnostics["process_id"] = getattr(error, "process_id", None)
                diagnostics["termination_reason"] = type(error).__name__
                raise
            latency_ms = (perf_counter() - started) * 1000
            diagnostics["elapsed_ms"] = latency_ms
            diagnostics["process_id"] = result.process_id
            completed_at = datetime.now(UTC)
            try:
                events = parse_codex_jsonl(result.stdout)
            except Exception as error:
                diagnostics["parser_state"] = "failed"
                diagnostics["termination_reason"] = type(error).__name__
                raise
            diagnostics["parser_state"] = "parsed"
            diagnostics["request_id"] = events.thread_id
            diagnostics["termination_reason"] = (
                "completed" if events.terminal_completed and result.exit_code == 0 else "failed"
            )
            if self._record_raw_events:
                self._write_sanitized_events(directory / "codex-events.jsonl", result.stdout)
            self._raise_terminal_failure(result, events)
            if not events.terminal_completed:
                raise CodexCLIMissingFinalResponseError(
                    "Codex CLI exited without a terminal turn.completed event"
                )
            if not output_path.is_file():
                raise CodexCLIMissingFinalResponseError(
                    "Codex CLI produced no structured final-output file"
                )
            output_path.chmod(0o600)
            try:
                output = output_type.model_validate_json(
                    output_path.read_text(encoding="utf-8"), strict=True
                )
            except (OSError, ValidationError) as error:
                raise CodexCLIInvalidStructuredOutputError(
                    "Codex CLI final output failed canonical schema validation"
                ) from error
            if len(events.final_messages) != 1:
                raise CodexCLIMissingFinalResponseError(
                    "Codex CLI JSONL contained no unique final agent response"
                )
            try:
                event_output = output_type.model_validate_json(
                    events.final_messages[0], strict=True
                )
            except ValidationError as error:
                raise CodexCLIInvalidStructuredOutputError(
                    "Codex CLI JSONL final response failed canonical schema validation"
                ) from error
            if event_output != output:
                raise CodexCLIConflictingFinalResponseError(
                    "Codex CLI JSONL and final-output file contain conflicting responses"
                )
            notes = tuple(
                [f"unknown_event:{event_type}" for event_type in events.unknown_event_types]
                + (["token_usage_unavailable"] if events.token_usage is None else [])
                + (["sanitized_raw_events_preserved"] if self._record_raw_events else [])
            )
            metadata = ProviderMetadata(
                provider="codex",
                invocation_id=invocation_id,
                provider_surface="Codex CLI using authenticated ChatGPT access",
                provider_version=self._capabilities.version,
                model=self._model,
                request_id=events.thread_id,
                token_usage=events.token_usage,
                latency_ms=latency_ms,
                prompt_version=prompt_version,
                validation_result="valid",
                telemetry_notes=notes,
                started_at=started_at,
                completed_at=completed_at,
                subprocess_exit_code=result.exit_code,
            )
            return output, metadata, events
        except Exception as error:
            if diagnostics["termination_reason"] in {"not_started", "completed"}:
                diagnostics["termination_reason"] = type(error).__name__
            raise
        finally:
            if self._preserve_debug_directory:
                self._write_diagnostics(directory / "codex-diagnostics.json", diagnostics)
            else:
                try:
                    shutil.rmtree(directory)
                except OSError as error:
                    raise CodexCLITemporaryDirectoryError(
                        f"could not remove isolated Codex directory: {error}"
                    ) from error

    async def execute_canonical(
        self,
        *,
        prompt: str,
        output_type: type[OutputT],
        prompt_version: str,
    ) -> tuple[OutputT, ProviderMetadata, ParsedCodexEvents]:
        """Transport canonical JSON in a strict envelope, then validate it locally."""
        canonical_schema = json.dumps(output_type.model_json_schema(), separators=(",", ":"))
        envelope_prompt = (
            f"{prompt}\n\n"
            "Return an object with one field named payload. Its value must be a JSON string "
            "containing the exact canonical response object requested above. The decoded payload "
            "must validate against this canonical JSON Schema:\n"
            f"{canonical_schema}"
        )
        envelope, metadata, events = await self.execute(
            prompt=envelope_prompt,
            output_type=CodexCanonicalEnvelope,
            prompt_version=prompt_version,
        )
        try:
            output = output_type.model_validate_json(envelope.payload, strict=True)
        except ValidationError as error:
            raise CodexCLIInvalidStructuredOutputError(
                "Codex CLI canonical payload failed schema validation"
            ) from error
        return output, metadata, events

    def _create_directory(self) -> Path:
        root = Path(self._temporary_directory_root or tempfile.gettempdir()).resolve()
        if any((candidate / ".git").exists() for candidate in (root, *root.parents)):
            raise CodexCLITemporaryDirectoryError(
                "Codex CLI temporary directories must not be created inside a Git repository"
            )
        try:
            path = Path(
                tempfile.mkdtemp(
                    prefix="sim-pilot-codex-",
                    dir=root,
                )
            )
            path.chmod(0o700)
            return path
        except OSError as error:
            raise CodexCLITemporaryDirectoryError(
                f"could not create isolated Codex directory: {error}"
            ) from error

    @staticmethod
    def _write_schema(path: Path, output_type: type[BaseModel]) -> None:
        try:
            path.write_text(
                json.dumps(codex_output_schema(output_type), indent=2) + "\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
        except OSError as error:
            raise CodexCLISchemaFileError(
                f"could not write Codex output schema: {error}"
            ) from error

    @staticmethod
    def _write_sanitized_events(path: Path, stdout: bytes) -> None:
        safe_events: list[str] = []
        home = str(Path.home())
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            for line in stdout.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                value = JSON_OBJECT_ADAPTER.validate_json(line)
                event_type = value.get("type")
                if event_type == "item.completed":
                    raw_item = value.get("item")
                    item = (
                        JSON_OBJECT_ADAPTER.validate_python(raw_item)
                        if isinstance(raw_item, dict)
                        else {}
                    )
                    if item.get("type") != "agent_message":
                        continue
                elif event_type not in {
                    "thread.started",
                    "turn.started",
                    "turn.completed",
                    "turn.failed",
                    "error",
                }:
                    continue
                serialized = json.dumps(value, separators=(",", ":"))
                serialized = serialized.replace(home, "[HOME]")
                serialized = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", serialized)
                safe_events.append(serialized)
            temporary.write_text("\n".join(safe_events) + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(path)
            path.chmod(0o600)
        except (OSError, UnicodeDecodeError, ValidationError) as error:
            raise CodexCLISchemaFileError(
                f"could not preserve sanitized Codex events: {error}"
            ) from error
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _write_diagnostics(path: Path, diagnostics: Mapping[str, object]) -> None:
        temporary = path.with_name(f".{path.name}.tmp")
        try:
            temporary.write_text(json.dumps(diagnostics, indent=2) + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(path)
            path.chmod(0o600)
        except OSError as error:
            raise CodexCLISchemaFileError(
                f"could not preserve Codex diagnostics: {error}"
            ) from error
        finally:
            temporary.unlink(missing_ok=True)

    def _command(
        self,
        directory: Path,
        schema_path: Path,
        output_path: Path,
    ) -> tuple[str, ...]:
        return (
            str(self._capabilities.executable_path),
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--json",
            "--sandbox",
            "read-only",
            "-c",
            'approval_policy="never"',
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "--model",
            self._model,
            "--cd",
            str(directory),
            "--skip-git-repo-check",
            "-",
        )

    @staticmethod
    def _environment() -> dict[str, str]:
        allowed = (
            "PATH",
            "HOME",
            "CODEX_HOME",
            "LANG",
            "LC_ALL",
            "TMPDIR",
            "CODEX_CA_CERTIFICATE",
            "SSL_CERT_FILE",
        )
        environment = {key: os.environ[key] for key in allowed if key in os.environ}
        environment.setdefault("LANG", "C.UTF-8")
        return environment

    @staticmethod
    def _raise_terminal_failure(result: ProcessResult, events: ParsedCodexEvents) -> None:
        stderr = result.stderr.decode("utf-8", errors="replace")[:2_000]
        combined = " ".join((*events.error_messages, stderr)).lower()
        if "usage limit" in combined or "rate limit" in combined or "credits" in combined:
            raise CodexCLIUsageLimitError("Codex CLI reported a plan usage or credit limit")
        if (
            "not logged in" in combined
            or "authentication" in combined
            or "unauthorized" in combined
        ):
            raise CodexCLIAuthenticationExpiredError("Codex CLI authentication was rejected")
        if "sandbox" in combined and (events.terminal_failed or result.exit_code != 0):
            raise CodexCLISandboxError("Codex CLI could not establish the required sandbox")
        if "refus" in combined:
            raise CodexCLIRefusalError("Codex CLI refused the structured provider request")
        if events.terminal_failed or result.exit_code != 0:
            event_error = "; ".join(events.error_messages)
            stderr_detail = stderr.replace("Reading additional input from stdin...", "").strip()
            raise CodexCLINonzeroExitError(
                f"Codex CLI exited with status {result.exit_code}: "
                f"{event_error or stderr_detail or 'turn failed'}"
            )
