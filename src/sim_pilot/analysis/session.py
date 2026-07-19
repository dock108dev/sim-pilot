"""Owner-only local analysis session records for evidence and entity drill-down."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.analysis.contracts import AnalysisResponse
from sim_pilot.domain.world import WorldSnapshot
from sim_pilot.private_files import atomic_write_private_text

ANALYSIS_ID_PATTERN = re.compile(r"analysis:[0-9a-f]{20}")


class AnalysisSessionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    analysis_id: str = Field(pattern=r"^analysis:[0-9a-f]{20}$")
    response: AnalysisResponse
    snapshot: WorldSnapshot


class AnalysisSessionStore:
    def __init__(self, directory: Path) -> None:
        self._directory = directory

    def save(self, response: AnalysisResponse, snapshot: WorldSnapshot) -> AnalysisSessionRecord:
        material = "|".join(
            (
                response.snapshot_id,
                response.request.model_dump_json(),
                response.generated_at.isoformat(),
            )
        )
        analysis_id = f"analysis:{hashlib.sha256(material.encode()).hexdigest()[:20]}"
        record = AnalysisSessionRecord(
            analysis_id=analysis_id,
            response=response,
            snapshot=snapshot,
        )
        serialized = record.model_dump_json(indent=2)
        atomic_write_private_text(self._record_path(analysis_id), serialized)
        atomic_write_private_text(self._directory / "latest", f"{analysis_id}\n")
        return record

    def load(self, analysis_id: str | None = None) -> AnalysisSessionRecord:
        identifier = analysis_id or self._latest_id()
        path = self._record_path(identifier)
        if not path.is_file():
            raise ValueError(f"analysis session {identifier!r} was not found")
        return AnalysisSessionRecord.model_validate_json(
            path.read_text(encoding="utf-8"), strict=True
        )

    def _latest_id(self) -> str:
        path = self._directory / "latest"
        if not path.is_file():
            raise ValueError("no previous analysis session is available")
        return path.read_text(encoding="utf-8").strip()

    def _record_path(self, analysis_id: str) -> Path:
        if ANALYSIS_ID_PATTERN.fullmatch(analysis_id) is None:
            raise ValueError("analysis ID has an invalid format")
        return self._directory / f"{analysis_id.replace(':', '-')}.json"
