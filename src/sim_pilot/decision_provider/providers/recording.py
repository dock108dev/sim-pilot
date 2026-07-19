"""Opt-in atomic local recording for runtime decision provider calls."""

from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from sim_pilot.decision_provider.models import DecisionRecording, utc_timestamp
from sim_pilot.domain.models import JsonValue
from sim_pilot.runtime.decision_context import (
    DecisionContext,
    DecisionProviderResult,
)
from sim_pilot.runtime.decision_errors import DecisionRecordingError
from sim_pilot.runtime.interfaces import DecisionProvider

REDACTED = "[REDACTED]"
SENSITIVE_KEYS = ("api_key", "authorization", "credential", "password", "secret", "token")


class RecordingDecisionProvider:
    """Record a validated decision before releasing it to runtime execution."""

    def __init__(self, provider: DecisionProvider, directory: Path) -> None:
        self._provider = provider
        self._directory = directory

    async def decide(self, context: DecisionContext) -> DecisionProviderResult:
        recording_invocation_id = str(uuid4())
        result = await self._provider.decide(context)
        raw_context = cast("dict[str, JsonValue]", context.model_dump(mode="json"))
        recording_id = uuid5(
            NAMESPACE_URL,
            "sim-pilot:decision-recording:"
            f"{context.canonical_json()}:{result.decision.model_dump_json()}:"
            f"{result.metadata.provider}:{result.metadata.request_id}",
        )
        recording = DecisionRecording(
            id=recording_id,
            invocation_id=result.metadata.invocation_id or recording_invocation_id,
            captured_at=utc_timestamp(),
            context=cast("dict[str, JsonValue]", _redact(raw_context)),
            response=result.decision,
            metadata=result.metadata,
            validation_result=result.metadata.validation_result or "valid",
        )
        try:
            self._write(recording)
        except OSError as error:
            raise DecisionRecordingError(
                f"decision recording failed before execution: {error}"
            ) from error
        return result

    def _write(self, recording: DecisionRecording) -> None:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        stem = f"{recording.captured_at.strftime('%Y%m%dT%H%M%S%fZ')}-{recording.id}"
        destination = self._directory / f"{stem}.json"
        temporary = self._directory / f".{stem}.tmp"
        try:
            temporary.write_text(recording.model_dump_json(indent=2) + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def _redact(value: JsonValue, key: str = "") -> JsonValue:
    lowered = key.lower()
    if any(part in lowered for part in SENSITIVE_KEYS):
        return REDACTED
    if isinstance(value, dict):
        return {item_key: _redact(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value
