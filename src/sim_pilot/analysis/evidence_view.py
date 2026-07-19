"""Human-readable evidence and canonical entity drill-down."""

from __future__ import annotations

from collections.abc import Sequence

from sim_pilot.analysis.contracts import AnalysisFinding, AnalysisSubjectType
from sim_pilot.analysis.session import AnalysisSessionRecord
from sim_pilot.domain.world import (
    Company,
    Industry,
    Route,
    Station,
    Town,
    Vehicle,
    WorldSnapshot,
)

Entity = Company | Industry | Route | Station | Town | Vehicle


def entity_aliases(snapshot: WorldSnapshot, subject: AnalysisSubjectType) -> dict[str, str]:
    values = _collection(snapshot, subject)
    prefix = {
        AnalysisSubjectType.COMPANY: "C",
        AnalysisSubjectType.TOWN: "T",
        AnalysisSubjectType.INDUSTRY: "I",
        AnalysisSubjectType.STATION: "S",
        AnalysisSubjectType.VEHICLE: "V",
        AnalysisSubjectType.ROUTE: "R",
    }[subject]
    return {item.id: f"{prefix}-{index:03d}" for index, item in enumerate(values, 1)}


def resolve_entity(
    snapshot: WorldSnapshot,
    subject: AnalysisSubjectType,
    reference: str,
) -> Entity:
    values = _collection(snapshot, subject)
    aliases = entity_aliases(snapshot, subject)
    normalized = reference.upper()
    matches = [
        item
        for item in values
        if item.id == reference
        or aliases[item.id] == normalized
        or item.id.startswith(reference)
        or item.id.endswith(reference)
        or getattr(item, "name", "").casefold() == reference.casefold()
    ]
    if not matches:
        raise ValueError(f"no {subject.value} matches {reference!r}")
    if len(matches) != 1:
        raise ValueError(f"{subject.value} reference {reference!r} is ambiguous")
    return matches[0]


def render_session_summary(record: AnalysisSessionRecord) -> str:
    response = record.response
    lines = [
        f"Analysis: {record.analysis_id}",
        f"Snapshot: {response.snapshot_id}",
        f"Question: {response.request.question}",
        f"Status: {response.status.value}",
        f"Findings: {len(response.findings)}",
    ]
    lines.extend(
        f"- {item.finding_id}: {item.severity.value} — {item.title}" for item in response.findings
    )
    lines.append("Use `sim-pilot analysis evidence ANALYSIS_ID FINDING_ID` for details.")
    return "\n".join(lines)


def render_finding_evidence(record: AnalysisSessionRecord, finding_id: str) -> str:
    finding = next(
        (item for item in record.response.findings if item.finding_id == finding_id), None
    )
    if finding is None:
        raise ValueError(f"finding {finding_id!r} is not part of {record.analysis_id}")
    lines = [
        f"Finding: {finding.title}",
        f"Kind: {finding.kind.value}",
        f"Severity: {finding.severity.value}",
        f"Confidence: {finding.confidence.value}",
        f"Summary: {finding.summary}",
        "",
        "Evidence",
    ]
    for index, evidence in enumerate(finding.evidence, 1):
        subject = (
            "world"
            if evidence.entity_type is None
            else _entity_label(record.snapshot, evidence.entity_type, evidence.entity_id)
        )
        lines.append(f"{index}. {subject} — {evidence.field}")
        lines.append(f"   observed: {evidence.observed_value}")
        if evidence.comparison_snapshot_id is not None:
            lines.append(f"   comparison: {evidence.comparison_value}")
        if evidence.metric_inputs:
            inputs = ", ".join(
                f"{key}={value}" for key, value in sorted(evidence.metric_inputs.items())
            )
            lines.append(f"   inputs: {inputs}")
    if finding.limitations:
        lines.extend(("", "Limitations"))
        lines.extend(f"- {item}" for item in finding.limitations)
    return "\n".join(lines)


def render_entity(
    snapshot: WorldSnapshot,
    subject: AnalysisSubjectType,
    reference: str,
    findings: Sequence[AnalysisFinding] = (),
) -> str:
    entity = resolve_entity(snapshot, subject, reference)
    alias = entity_aliases(snapshot, subject)[entity.id]
    lines = [
        f"{subject.value.title()} {alias}",
        f"Canonical ID: {entity.id}",
    ]
    name = getattr(entity, "name", None)
    if name is not None:
        lines.append(f"Name: {name}")
    lines.extend(_entity_metrics(entity))
    related = [
        item
        for item in findings
        if any(evidence.entity_id == entity.id for evidence in item.evidence)
    ]
    lines.extend(("", "Current findings"))
    if related:
        lines.extend(f"- {item.severity.value}: {item.title}" for item in related)
    else:
        lines.append("- No finding in this analysis directly references the entity.")
    lines.extend(("", "Limitations"))
    lines.append("Entity aliases are snapshot-local; the canonical ID remains authoritative.")
    if isinstance(entity, Route):
        lines.append("Route identity is inferred from normalized vehicle orders.")
    return "\n".join(lines)


def _entity_metrics(entity: Entity) -> list[str]:
    if isinstance(entity, Company):
        company_value = entity.company_value if entity.company_value is not None else "unknown"
        return [
            f"Cash: {entity.cash}",
            f"Loan: {entity.loan}",
            f"Company value: {company_value}",
            f"Stations: {entity.station_count}",
        ]
    if isinstance(entity, Vehicle):
        return [
            f"Type: {entity.type}",
            f"Last-year profit: {entity.profit_last_year}",
            f"Current-year profit: {entity.profit_this_year}",
            f"State: {entity.running_state}; in depot: {str(entity.in_depot).lower()}",
            f"Route: {entity.route_id or 'not inferred'}",
        ]
    if isinstance(entity, Station):
        waiting = sum(item.waiting or 0 for item in entity.waiting_cargo)
        return [
            f"Waiting cargo: {waiting}",
            f"Observed vehicles: {entity.vehicle_count}",
            f"Served towns: {len(entity.served_town_ids)}",
            f"Served industries: {len(entity.served_industry_ids)}",
        ]
    if isinstance(entity, Route):
        distance = entity.estimated_distance
        return [
            f"Type: {entity.inferred_route_type}",
            f"Vehicles: {len(entity.vehicle_ids)}",
            f"Stations: {len(entity.ordered_station_ids)}",
            f"Estimated distance: {distance if distance is not None else 'unknown'}",
        ]
    if isinstance(entity, Town):
        station_count = entity.station_count
        return [
            f"Population: {entity.population}",
            f"Company stations: {station_count if station_count is not None else 'unknown'}",
            f"Growth: {entity.growth_state or 'unknown'}",
        ]
    production = sum(item.produced or 0 for item in entity.production)
    return [
        f"Type: {entity.type}",
        f"Observed production: {production}",
        f"Nearby company stations: {len(entity.nearby_station_ids)}",
    ]


def _entity_label(
    snapshot: WorldSnapshot,
    subject: AnalysisSubjectType,
    entity_id: str | None,
) -> str:
    if entity_id is None:
        return subject.value
    alias = entity_aliases(snapshot, subject).get(entity_id)
    return f"{alias or entity_id} ({subject.value})"


def _collection(snapshot: WorldSnapshot, subject: AnalysisSubjectType) -> tuple[Entity, ...]:
    values: dict[AnalysisSubjectType, tuple[Entity, ...]] = {
        AnalysisSubjectType.COMPANY: snapshot.companies,
        AnalysisSubjectType.TOWN: snapshot.towns,
        AnalysisSubjectType.INDUSTRY: snapshot.industries,
        AnalysisSubjectType.STATION: snapshot.stations,
        AnalysisSubjectType.VEHICLE: snapshot.vehicles,
        AnalysisSubjectType.ROUTE: snapshot.routes,
    }
    if subject is AnalysisSubjectType.WORLD:
        raise ValueError("world is not a drill-down entity type")
    return values[subject]
