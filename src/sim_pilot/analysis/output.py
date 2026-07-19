"""Player-facing compact and detailed rendering for analysis responses."""

from __future__ import annotations

from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisResponse,
    AnalysisStatus,
    AnalysisSubjectType,
    FindingKind,
)
from sim_pilot.analysis.evidence_view import entity_aliases
from sim_pilot.domain.world import WorldSnapshot


def render_analysis(
    response: AnalysisResponse,
    *,
    detailed: bool = False,
    snapshot: WorldSnapshot | None = None,
    snapshot_age_seconds: float = 0,
    cached: bool = False,
) -> str:
    """Render a deterministic answer with claims separated by epistemic role."""
    title = response.request.analysis_type.value.replace("_", " ").title()
    lines = [f"{title}: {_status_label(response)}", "", "Fact", response.answer]

    findings = tuple(item for item in response.findings if item.kind is FindingKind.OBSERVED_FACT)
    inferences = tuple(
        item for item in response.findings if item.kind is FindingKind.INFERRED_FINDING
    )
    quality = tuple(item for item in response.findings if item.kind is FindingKind.DATA_QUALITY)
    _render_finding_group(lines, "Finding", findings, response, snapshot, detailed)
    _render_finding_group(lines, "Inference", inferences, response, snapshot, detailed)
    _render_finding_group(lines, "Data quality", quality, response, snapshot, detailed)

    if not response.findings:
        lines.extend(("", "Finding", _no_result_message(response)))

    lines.extend(("", "Recommendation"))
    if response.recommendations:
        for item in sorted(response.recommendations, key=lambda value: value.priority):
            lines.append(f"- Inspect: {item.title}. {item.rationale}")
            if detailed and item.limitations:
                lines.extend(f"  Limitation: {value}" for value in item.limitations)
    else:
        lines.append(f"- {_next_question(response)}")

    if response.explanation is not None:
        lines.extend(("", "Model explanation"))
        lines.extend(f"- {item.text}" for item in response.explanation.statements)

    limitations = _limitations(response)
    lines.extend(("", "Limitation"))
    lines.extend(f"- {item}" for item in limitations)

    if response.request.ranking is not None:
        lines.extend(("", "Ranking"))
        metric = response.request.ranking.metric.value.replace("_", " ")
        period = (
            "last year"
            if "last_year" in response.request.ranking.metric.value
            else "observed snapshot"
        )
        lines.append(f"Metric: {metric} ({period})")
        if snapshot is not None:
            evaluated = _evaluated_count(response, snapshot)
            lines.append(f"Evaluated: {evaluated}; excluded for missing metric: 0")
        lines.append("Tie-break: canonical entity ID, ascending.")

    if detailed and snapshot is not None:
        metadata = snapshot.metadata
        source = "cached" if cached else "fresh or selected"
        lines.extend(
            (
                "",
                "Snapshot",
                f"ID: {metadata.snapshot_id}",
                f"World: {metadata.world_id}; save generation: {metadata.save_generation}",
                f"Captured: {metadata.captured_at.isoformat()}",
                f"Age: {snapshot_age_seconds:.1f}s; source: {source}",
                f"Complete: {str(metadata.complete).lower()}",
            )
        )
    lines.extend(("", "Ask next", _next_question(response)))
    return "\n".join(lines)


def _render_finding_group(
    lines: list[str],
    heading: str,
    findings: tuple[AnalysisFinding, ...],
    response: AnalysisResponse,
    snapshot: WorldSnapshot | None,
    detailed: bool,
) -> None:
    if not findings:
        return
    lines.extend(("", heading))
    for finding in findings:
        identity = _finding_identity(finding, snapshot)
        metric = ""
        if finding.metric_name is not None:
            metric = f"; {finding.metric_name}={finding.metric_value}"
        lines.append(
            f"- {identity}{finding.title} [{finding.severity.value}, "
            f"confidence {finding.confidence.value}{metric}]"
        )
        lines.append(f"  {finding.summary}")
        if detailed:
            lines.append(f"  Finding ID: {finding.finding_id}")
            for evidence in finding.evidence:
                lines.append(
                    f"  Evidence: {evidence.field}={evidence.observed_value} "
                    f"(snapshot {evidence.snapshot_id})"
                )
    del response


def _finding_identity(finding: AnalysisFinding, snapshot: WorldSnapshot | None) -> str:
    if snapshot is None:
        return ""
    labels: list[str] = []
    for evidence in finding.evidence:
        if evidence.entity_type is None or evidence.entity_id is None:
            continue
        aliases = entity_aliases(snapshot, evidence.entity_type)
        labels.append(aliases.get(evidence.entity_id, evidence.entity_id))
    unique = tuple(dict.fromkeys(labels))
    return "" if not unique else f"{', '.join(unique)} — "


def _limitations(response: AnalysisResponse) -> tuple[str, ...]:
    values = [*response.limitations]
    for finding in response.findings:
        values.extend(finding.limitations)
    if not values:
        return ("No material limitation was recorded for this analysis.",)
    return tuple(dict.fromkeys(values))


def _status_label(response: AnalysisResponse) -> str:
    if any(item.severity.value == "critical" for item in response.findings):
        return "Critical"
    if any(item.severity.value == "warning" for item in response.findings):
        return "Warning"
    return response.status.value.replace("_", " ").title()


def _no_result_message(response: AnalysisResponse) -> str:
    if response.status is AnalysisStatus.INSUFFICIENT_DATA:
        return "The snapshot did not contain enough supported evidence to answer this question."
    return "No major supported issue was detected in the selected findings."


def _next_question(response: AnalysisResponse) -> str:
    suggestions = {
        "company_health": "Ask which vehicles are losing the most money.",
        "financial_summary": "Ask whether debt is high relative to company value.",
        "vehicle_performance": "Ask which routes contain the losing vehicles.",
        "station_performance": "Ask which station has the most waiting cargo.",
        "route_performance": "Inspect the highest-priority route and its vehicles.",
        "world_changes": "Ask which observed change deserves attention first.",
    }
    return suggestions.get(
        response.request.analysis_type.value,
        "Ask for a detailed view or inspect the evidence for a finding.",
    )


def _evaluated_count(response: AnalysisResponse, snapshot: WorldSnapshot) -> int:
    subject = response.request.subject_type
    if subject is None:
        subject = {
            "vehicle_performance": AnalysisSubjectType.VEHICLE,
            "station_performance": AnalysisSubjectType.STATION,
            "route_performance": AnalysisSubjectType.ROUTE,
            "town_coverage": AnalysisSubjectType.TOWN,
            "industry_opportunities": AnalysisSubjectType.INDUSTRY,
        }.get(response.request.analysis_type.value)
    if subject is AnalysisSubjectType.COMPANY:
        return len(snapshot.companies)
    if subject is AnalysisSubjectType.VEHICLE:
        return len(snapshot.vehicles)
    if subject is AnalysisSubjectType.STATION:
        return len(snapshot.stations)
    if subject is AnalysisSubjectType.ROUTE:
        return len(snapshot.routes)
    if subject is AnalysisSubjectType.TOWN:
        return len(snapshot.towns)
    if subject is AnalysisSubjectType.INDUSTRY:
        return len(snapshot.industries)
    return 0
