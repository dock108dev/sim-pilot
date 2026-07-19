"""Strict JSONL parsing and forward-compatible unknown events."""

import json

import pytest

from sim_pilot.provider_support.codex_cli.errors import (
    CodexCLIConflictingFinalResponseError,
    CodexCLIMalformedJSONLError,
    CodexCLITelemetryError,
)
from sim_pilot.provider_support.codex_cli.events import parse_codex_jsonl


def _lines(*events: dict[str, object]) -> bytes:
    return ("\n".join(json.dumps(event) for event in events) + "\n").encode()


def test_parser_extracts_thread_final_message_usage_and_unknown_event() -> None:
    parsed = parse_codex_jsonl(
        _lines(
            {"type": "thread.started", "thread_id": "thread_1"},
            {"type": "future.event"},
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": '{"ok":true}'},
            },
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 10,
                    "cached_input_tokens": 4,
                    "output_tokens": 3,
                    "reasoning_output_tokens": 2,
                },
            },
        )
    )

    assert parsed.thread_id == "thread_1"
    assert parsed.final_messages == ('{"ok":true}',)
    assert parsed.unknown_event_types == ("future.event",)
    assert parsed.token_usage is not None
    assert parsed.token_usage.cached_input_tokens == 4
    assert parsed.token_usage.output_tokens == 5
    assert parsed.token_usage.total_tokens == 15


def test_parser_rejects_malformed_conflicting_and_multiple_terminal_events() -> None:
    with pytest.raises(CodexCLIMalformedJSONLError):
        parse_codex_jsonl(b"not-json\n")
    with pytest.raises(CodexCLIConflictingFinalResponseError):
        parse_codex_jsonl(
            _lines(
                {"type": "item.completed", "item": {"type": "agent_message", "text": "a"}},
                {"type": "item.completed", "item": {"type": "agent_message", "text": "b"}},
            )
        )
    with pytest.raises(CodexCLITelemetryError):
        parse_codex_jsonl(_lines({"type": "turn.completed"}, {"type": "turn.failed"}))
