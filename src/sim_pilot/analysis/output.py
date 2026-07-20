"""Player-facing compact and detailed rendering for analysis responses."""

from __future__ import annotations

from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisResponse,
    AnalysisStatus,
    AnalysisSubjectType,
    FindingKind,
)
from sim_pilot.analysis.evidence_view import entity_display_labels
from sim_pilot.domain.world import WorldSnapshot


def render_analysis(
    response: AnalysisResponse,
    *,
    detailed: bool = False,
    snapshot: WorldSnapshot | None = None,
    snapshot_age_seconds: float = 0,
    cached: bool = False,
    evidence: bool = False,
) -> str:
    """Render a deterministic answer with claims separated by epistemic role."""
    if not detailed and response.presentation is not None:
        return _render_compact(response, snapshot, evidence=evidence)
    title = response.request.analysis_type.value.replace("_", " ").title()
    lines = [response.answer, "", f"{title}: {_status_label(response)}"]

    visible_findings = response.findings if detailed else response.findings[:2]
    findings = tuple(item for item in visible_findings if item.kind is FindingKind.OBSERVED_FACT)
    inferences = tuple(
        item for item in visible_findings if item.kind is FindingKind.INFERRED_FINDING
    )
    quality = tuple(item for item in visible_findings if item.kind is FindingKind.DATA_QUALITY)
    _render_finding_group(lines, "Finding", findings, response, snapshot, detailed)
    _render_finding_group(lines, "Inference", inferences, response, snapshot, detailed)
    _render_finding_group(lines, "Data quality", quality, response, snapshot, detailed)

    if not response.findings:
        lines.extend(("", "Finding", _no_result_message(response)))

    lines.extend(("", "Recommendation"))
    if response.recommendations:
        recommendations = sorted(response.recommendations, key=lambda value: value.priority)
        for item in recommendations if detailed else recommendations[:1]:
            lines.append(f"- Inspect: {item.title}. {item.rationale}")
            if detailed and item.limitations:
                lines.extend(f"  Limitation: {value}" for value in item.limitations)
    else:
        lines.append(f"- {_next_question(response)}")

    if response.explanation is not None:
        lines.extend(("", "Model explanation"))
        statements = response.explanation.statements
        selected_statements = statements if detailed else statements[:2]
        lines.extend(f"- {item.text}" for item in selected_statements)

    limitations = _limitations(response)
    lines.extend(("", "Limitation"))
    selected_limitations = limitations if detailed else limitations[:1]
    lines.extend(f"- {item}" for item in selected_limitations)

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
            evaluated = (
                _evaluated_count(response, snapshot)
                if response.presentation is None
                else response.presentation.evaluated_count
            )
            excluded = 0 if response.presentation is None else response.presentation.excluded_count
            lines.append(
                f"Evaluated: {evaluated or 0}; excluded for missing metric: {excluded or 0}"
            )
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


def _render_compact(
    response: AnalysisResponse,
    snapshot: WorldSnapshot | None,
    *,
    evidence: bool = False,
) -> str:
    presentation = response.presentation
    assert presentation is not None
    lines = [presentation.direct_answer]
    finding = next(
        (item for item in response.findings if item.finding_id == presentation.decisive_finding_id),
        None,
    )
    if finding is not None:
        lines.extend(("", "Evidence", _compact_evidence(finding, snapshot)))
    recommendation = next(
        (
            item
            for item in response.recommendations
            if item.recommendation_id == presentation.recommendation_id
        ),
        None,
    )
    if recommendation is not None:
        lines.extend(("", "Inspect next", recommendation.rationale))
    elif presentation.follow_up is not None:
        lines.extend(("", "Inspect next", presentation.follow_up))
    if response.explanation is not None:
        lines.extend(("", "Why it matters", response.explanation.statements[0].text))
    if presentation.limitation is not None:
        lines.extend(("", "Limitation", presentation.limitation))
    if evidence and finding is not None:
        lines.extend(("", "Evidence details"))
        for item in finding.evidence:
            lines.append(f"- {item.field}: {item.observed_value}")
            if item.metric_inputs:
                inputs = ", ".join(
                    f"{key}={value}" for key, value in sorted(item.metric_inputs.items())
                )
                lines.append(f"  Inputs: {inputs}")
    return "\n".join(lines)


def _compact_evidence(finding: AnalysisFinding, snapshot: WorldSnapshot | None) -> str:
    identity = _finding_identity(finding, snapshot).removesuffix(" — ")
    prefix = f"{identity}: " if identity else ""
    value = finding.metric_value
    if finding.metric_name in {
        "cash",
        "loan",
        "net_operating_result",
        "profit_this_year",
        "profit_last_year",
        "route_aggregate_profit",
        "vehicle_type_aggregate_profit",
    } and isinstance(value, (int, float)):
        return f"{prefix}{finding.metric_name.replace('_', ' ')} is {_currency(value)}."
    return f"{prefix}{finding.summary}"


def _currency(value: int | float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}£{abs(value):,.0f}"


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
        aliases = entity_display_labels(snapshot, evidence.entity_type)
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
