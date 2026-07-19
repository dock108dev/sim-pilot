"""Concise stderr progress for interactive intelligence commands."""

from __future__ import annotations

from collections.abc import Callable

from sim_pilot.domain.world import WorldSnapshot


class AnalysisProgress:
    def __init__(self, *, quiet: bool, emit: Callable[[str], None]) -> None:
        self._quiet = quiet
        self._emit = emit

    def collecting(self) -> None:
        self._write("Collecting OpenTTD snapshot…")

    def analyzing(self, snapshot: WorldSnapshot) -> None:
        self._write(
            f"Analyzing {len(snapshot.vehicles)} vehicles and {len(snapshot.stations)} stations…"
        )

    def compiling(self) -> None:
        self._write("Interpreting question…")

    def explaining(self) -> None:
        self._write("Preparing explanation…")

    def _write(self, message: str) -> None:
        if not self._quiet:
            self._emit(message)
