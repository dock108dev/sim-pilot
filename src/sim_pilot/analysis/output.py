"""Concise and detailed terminal rendering for structured analysis responses."""

from __future__ import annotations

from sim_pilot.analysis.contracts import AnalysisResponse


def render_analysis(response: AnalysisResponse, *, detailed: bool = False) -> str:
    lines = [
        f"{response.request.analysis_type.value.replace('_', ' ').title()}: "
        f"{response.status.value.replace('_', ' ')}",
        "",
        response.answer,
    ]
    if response.findings:
        lines.extend(("", "Findings"))
        for index, finding in enumerate(response.findings, 1):
            metric = (
                ""
                if finding.metric_name is None
                else f" [{finding.metric_name}={finding.metric_value}]"
            )
            lines.append(f"{index}. {finding.severity.value}: {finding.title}{metric}")
            lines.append(f"   {finding.summary}")
            if detailed:
                lines.append(
                    f"   confidence={finding.confidence.value}; evidence="
                    f"{', '.join(item.field for item in finding.evidence)}"
                )
                for limitation in finding.limitations:
                    lines.append(f"   limitation: {limitation}")
    if response.recommendations:
        lines.extend(("", "Inspect next"))
        for item in response.recommendations:
            lines.append(f"- {item.title} (priority {item.priority}, executable=false)")
    if response.explanation is not None:
        lines.extend(("", "Model explanation"))
        lines.extend(f"- {item.text}" for item in response.explanation.statements)
    if response.limitations:
        lines.extend(("", "Limitations"))
        lines.extend(f"- {item}" for item in response.limitations)
    return "\n".join(lines)
