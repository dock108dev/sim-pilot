"""Owner-only local analysis session records for evidence and entity drill-down."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import suppress
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.analysis.compiler import (
    AnalysisCompilerContext,
    AnalysisEntityContext,
    AnalysisFindingContext,
)
from sim_pilot.analysis.contracts import AnalysisResponse, AnalysisSubjectType
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
        payload = json.loads(path.read_text(encoding="utf-8"))
        _add_legacy_inspection_guidance(payload)
        _add_legacy_snapshot_metadata(payload)
        return AnalysisSessionRecord.model_validate_json(json.dumps(payload), strict=True)

    def compiler_context(
        self,
        snapshot: WorldSnapshot,
        *,
        comparison_snapshot_id: str | None = None,
    ) -> AnalysisCompilerContext:
        """Build bounded context only from a compatible prior analysis."""
        try:
            record = self.load()
        except ValueError:
            return AnalysisCompilerContext(comparison_snapshot_id=comparison_snapshot_id)
        if not _context_compatible(record.snapshot, snapshot):
            return AnalysisCompilerContext(comparison_snapshot_id=comparison_snapshot_id)
        presentation = record.response.presentation
        decisive_id = None if presentation is None else presentation.decisive_finding_id
        displayed = tuple(
            item
            for item in record.response.findings
            if decisive_id is None or item.finding_id == decisive_id
        )[:1]
        focus: list[AnalysisEntityContext] = []
        for finding in displayed:
            for evidence in finding.evidence:
                subject = evidence.entity_type
                if subject is None or subject is AnalysisSubjectType.WORLD:
                    continue
                if evidence.entity_id is None:
                    continue
                entity = _current_entity(snapshot, subject, evidence.entity_id)
                if entity is None:
                    continue
                focus.append(
                    AnalysisEntityContext(
                        subject_type=subject,
                        canonical_id=evidence.entity_id,
                        alias=evidence.entity_id,
                        name=getattr(entity, "name", None),
                    )
                )
        unique_focus = tuple(
            {(item.subject_type, item.canonical_id): item for item in focus}.values()
        )
        return AnalysisCompilerContext(
            comparison_snapshot_id=comparison_snapshot_id,
            prior_analysis_id=record.analysis_id,
            focus_entities=unique_focus,
            prior_findings=tuple(
                AnalysisFindingContext(
                    finding_id=item.finding_id,
                    title=item.title,
                    entity_ids=tuple(
                        dict.fromkeys(
                            evidence.entity_id
                            for evidence in item.evidence
                            if evidence.entity_id is not None
                        )
                    ),
                )
                for item in displayed
            ),
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


def _context_compatible(previous: WorldSnapshot, current: WorldSnapshot) -> bool:
    return (
        previous.metadata.world_id == current.metadata.world_id
        and previous.metadata.save_generation == current.metadata.save_generation
        and previous.metadata.observer_company_id == current.metadata.observer_company_id
        and previous.metadata.capability_fingerprint == current.metadata.capability_fingerprint
    )


def _add_legacy_inspection_guidance(payload: object) -> None:
    """Keep pre-Phase-9.1 owner-only sessions readable without inventing guidance."""
    if not isinstance(payload, dict):
        return
    payload_dict = cast(dict[str, object], payload)
    response = payload_dict.get("response")
    if not isinstance(response, dict):
        return
    response_dict = cast(dict[str, object], response)
    presentation = response_dict.get("presentation")
    if not isinstance(presentation, dict) or "inspection_guidance" in presentation:
        return
    presentation_dict = cast(dict[str, object], presentation)
    presentation_dict["inspection_guidance"] = {
        "schema_version": 1,
        "status": "not_responsible",
        "target_entity_type": None,
        "target_entity_id": None,
        "target_label": None,
        "observation": None,
        "diagnostic_value": None,
        "unavailable_reason": (
            "this retained analysis predates typed inspection guidance; run the question again"
        ),
        "supporting_finding_ids": [],
    }


def _add_legacy_snapshot_metadata(payload: object) -> None:
    """Keep retained pre-Phase-9.2 sessions readable with honest provenance."""
    if not isinstance(payload, dict):
        return
    payload_dict = cast(dict[str, object], payload)
    response = payload_dict.get("response")
    snapshot = payload_dict.get("snapshot")
    if not isinstance(response, dict) or not isinstance(snapshot, dict):
        return
    response_dict = cast(dict[str, object], response)
    if "snapshot_metadata" in response_dict:
        return
    metadata = cast(dict[str, object], snapshot).get("metadata")
    if not isinstance(metadata, dict):
        return
    source = cast(dict[str, object], metadata)
    age = 0.0
    generated_at = response_dict.get("generated_at")
    captured_at = source.get("captured_at")
    if isinstance(generated_at, str) and isinstance(captured_at, str):
        with suppress(ValueError):
            age = max(
                0.0,
                (
                    datetime.fromisoformat(generated_at) - datetime.fromisoformat(captured_at)
                ).total_seconds(),
            )
    started = source.get("capture_started_game_date", 0)
    completed = source.get("capture_completed_game_date", started)
    response_dict["snapshot_metadata"] = {
        "schema_version": 1,
        "source": "supplied_snapshot",
        "snapshot_age_seconds": age,
        "maximum_acceptable_age_seconds": None,
        "collection_duration_seconds": None,
        "collection_interval_game_days": (
            completed - started if isinstance(started, int) and isinstance(completed, int) else 0
        ),
        "world_id": source.get("world_id"),
        "observer_company_id": source.get("observer_company_id"),
        "bridge_company_context": None,
        "save_generation": source.get("save_generation"),
        "capability_fingerprint": source.get("capability_fingerprint"),
        "snapshot_bridge_sequence": source.get("bridge_sequence"),
        "identity_verification_sequence": None,
        "identity_verified_at": None,
        "bridge_synchronization_state": "retained_session_metadata_only",
        "openttd_version": source.get("game_version"),
        "bridge_protocol_version": None,
        "bridge_script_version": None,
    }


def _current_entity(
    snapshot: WorldSnapshot,
    subject: AnalysisSubjectType,
    identifier: str,
) -> object | None:
    collections = {
        AnalysisSubjectType.COMPANY: snapshot.companies,
        AnalysisSubjectType.TOWN: snapshot.towns,
        AnalysisSubjectType.INDUSTRY: snapshot.industries,
        AnalysisSubjectType.STATION: snapshot.stations,
        AnalysisSubjectType.VEHICLE: snapshot.vehicles,
        AnalysisSubjectType.ROUTE: snapshot.routes,
    }
    return next(
        (item for item in collections.get(subject, ()) if item.id == identifier),
        None,
    )
