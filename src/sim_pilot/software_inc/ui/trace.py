"""Owner-only append-only evidence for Software Inc. UI cycles."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path

from .models import SoftwareIncUITraceRecord, StaffingTraceRecord

DEFAULT_TRACE_PATH = (
    Path.home()
    / "Library"
    / "Application Support"
    / "Sim Pilot"
    / "software-inc"
    / "ui"
    / "traces.jsonl"
)
DEFAULT_STAFFING_TRACE_PATH = DEFAULT_TRACE_PATH.with_name("staffing-traces.jsonl")


def append_ui_trace(record: SoftwareIncUITraceRecord, *, path: Path = DEFAULT_TRACE_PATH) -> Path:
    """Durably append one cycle without retaining screenshot pixels."""
    return _append_record(record.model_dump_json(), path)


def append_staffing_trace(
    record: StaffingTraceRecord,
    *,
    path: Path = DEFAULT_STAFFING_TRACE_PATH,
) -> Path:
    """Durably append an approval-bound staffing cycle without screenshot pixels."""
    return _append_record(record.model_dump_json(), path)


def _append_record(payload: str, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        with os.fdopen(descriptor, "ab", closefd=True) as stream:
            stream.write(payload.encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        raise
    path.chmod(0o600)
    return path


__all__ = [
    "DEFAULT_STAFFING_TRACE_PATH",
    "DEFAULT_TRACE_PATH",
    "append_staffing_trace",
    "append_ui_trace",
]
