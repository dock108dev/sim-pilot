"""Strict parsing for the bounded Codex JSONL event subset Sim Pilot consumes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from sim_pilot.provider_metadata import ProviderTokenUsage
from sim_pilot.provider_support.codex_cli.errors import (
    CodexCLIConflictingFinalResponseError,
    CodexCLIMalformedJSONLError,
    CodexCLITelemetryError,
)

EVENT_ADAPTER = TypeAdapter(dict[str, object])


class CodexUsage(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)

    input_tokens: int = Field(ge=0)
    cached_input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int = Field(ge=0)
    reasoning_output_tokens: int = Field(default=0, ge=0)


class ParsedCodexEvents(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    thread_id: str | None = None
    terminal_completed: bool
    terminal_failed: bool
    final_messages: tuple[str, ...] = ()
    token_usage: ProviderTokenUsage | None = None
    unknown_event_types: tuple[str, ...] = ()
    error_messages: tuple[str, ...] = ()


def parse_codex_jsonl(stdout: bytes) -> ParsedCodexEvents:
    thread_id: str | None = None
    completed = False
    failed = False
    final_messages: list[str] = []
    usage: CodexUsage | None = None
    unknown: list[str] = []
    errors: list[str] = []
    try:
        lines = stdout.decode("utf-8").splitlines()
    except UnicodeDecodeError as error:
        raise CodexCLIMalformedJSONLError("Codex JSONL is not valid UTF-8") from error
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            event = EVENT_ADAPTER.validate_json(raw_line)
        except ValidationError as error:
            raise CodexCLIMalformedJSONLError(
                f"Codex JSONL line {line_number} is malformed"
            ) from error
        raw_type = event.get("type")
        if not isinstance(raw_type, str):
            raise CodexCLIMalformedJSONLError(
                f"Codex JSONL line {line_number} lacks a string event type"
            )
        event_type = raw_type
        if event_type == "thread.started":
            candidate = event.get("thread_id")
            if isinstance(candidate, str):
                thread_id = candidate
        elif event_type == "turn.completed":
            if completed or failed:
                raise CodexCLITelemetryError("Codex JSONL contains multiple terminal turn events")
            completed = True
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                try:
                    usage = CodexUsage.model_validate(raw_usage, strict=True)
                except ValidationError as error:
                    raise CodexCLITelemetryError("Codex usage telemetry is invalid") from error
        elif event_type == "turn.failed":
            if completed or failed:
                raise CodexCLITelemetryError("Codex JSONL contains multiple terminal turn events")
            failed = True
            message = event.get("error")
            if isinstance(message, str):
                errors.append(message)
        elif event_type == "error":
            message = event.get("message")
            if isinstance(message, str):
                errors.append(message)
        elif event_type == "item.completed":
            item = event.get("item")
            typed_item = EVENT_ADAPTER.validate_python(item) if isinstance(item, dict) else {}
            if typed_item.get("type") == "agent_message":
                message = typed_item.get("text")
                if isinstance(message, str):
                    final_messages.append(message)
        elif event_type not in {"turn.started", "item.started", "item.updated"}:
            unknown.append(event_type)
    distinct_messages = tuple(dict.fromkeys(final_messages))
    if len(distinct_messages) > 1:
        raise CodexCLIConflictingFinalResponseError(
            "Codex JSONL contains multiple conflicting agent responses"
        )
    mapped_usage = (
        None
        if usage is None
        else ProviderTokenUsage(
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            output_tokens=usage.output_tokens + usage.reasoning_output_tokens,
            total_tokens=usage.input_tokens + usage.output_tokens + usage.reasoning_output_tokens,
        )
    )
    return ParsedCodexEvents(
        thread_id=thread_id,
        terminal_completed=completed,
        terminal_failed=failed,
        final_messages=distinct_messages,
        token_usage=mapped_usage,
        unknown_event_types=tuple(unknown),
        error_messages=tuple(errors),
    )
