"""Owner-only append-only evidence for Rail Route UI objectives."""

import os
from contextlib import suppress
from pathlib import Path

from sim_pilot.rail_route.ui.controller import RailRouteUIRouteResult

DEFAULT_TRACE_PATH = (
    Path.home() / "Library" / "Application Support" / "Sim Pilot" / "rail-route-ui" / "traces.jsonl"
)


def append_ui_trace(result: RailRouteUIRouteResult, *, path: Path = DEFAULT_TRACE_PATH) -> Path:
    """Durably append one complete result without retaining screenshot pixels."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        with os.fdopen(descriptor, "ab", closefd=True) as stream:
            stream.write(result.model_dump_json().encode("utf-8") + b"\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        with suppress(OSError):
            os.close(descriptor)
        raise
    path.chmod(0o600)
    return path
