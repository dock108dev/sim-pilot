"""Company-health and financial-summary analyzers."""

from __future__ import annotations

from sim_pilot.analysis.analyzers.base import AnalyzerResult
from sim_pilot.analysis.analyzers.support import add_result, make_finding, percentage_change
from sim_pilot.analysis.contracts import (
    AnalysisFinding,
    AnalysisRecommendation,
    AnalysisRequest,
    AnalysisStatus,
    AnalysisSubjectType,
    AnalysisType,
    EvidenceConfidence,
    FindingKind,
    FindingSeverity,
)
from sim_pilot.analysis.evidence import field_evidence, metric_evidence, observer_company
from sim_pilot.domain.world import Company, WorldSnapshot

ACCOUNTING_LIMITATION = (
    "Income and expenses may cover a partial or atypical accounting period; this is not a causal "
    "profitability model."
)


class CompanyHealthAnalyzer:
    analysis_type = AnalysisType.COMPANY_HEALTH

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del request
        company = observer_company(current)
        previous = _matching_company(comparison, company.id)
        findings: list[AnalysisFinding] = []
        recommendations: list[AnalysisRecommendation] = []
        confidence = (
            EvidenceConfidence.HIGH if current.metadata.complete else EvidenceConfidence.LOW
        )

        if company.income is not None and company.expenses is not None:
            net = company.income + company.expenses
            severity = FindingSeverity.WARNING if net < 0 else FindingSeverity.INFORMATIONAL
            add_result(
                findings,
                recommendations,
                make_finding(
                    snapshot=current,
                    analysis_type=self.analysis_type,
                    code="negative_operating_result" if net < 0 else "operating_result",
                    entity_ids=(company.id,),
                    kind=FindingKind.OBSERVED_FACT,
                    severity=severity,
                    title="Negative operating result" if net < 0 else "Positive operating result",
                    summary=f"Observed income plus expenses is {net}.",
                    metric_name="net_operating_result",
                    metric_value=net,
                    confidence=confidence,
                    evidence=(
                        metric_evidence(
                            current,
                            entity_type=AnalysisSubjectType.COMPANY,
                            entity_id=company.id,
                            field="net_operating_result",
                            value=net,
                            inputs={"income": company.income, "expenses": company.expenses},
                        ),
                    ),
                    limitations=(ACCOUNTING_LIMITATION,),
                    recommendation_code="review_operating_result" if net < 0 else None,
                ),
            )
            expense_magnitude = abs(company.expenses)
            liquidity = company.cash / max(expense_magnitude, 1)
            if liquidity < 1:
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="low_liquidity_reserve",
                        entity_ids=(company.id,),
                        kind=FindingKind.INFERRED_FINDING,
                        severity=FindingSeverity.WARNING,
                        title="Low observed liquidity reserve",
                        summary=(
                            f"Cash is {liquidity:.2f} times the magnitude of observed expenses."
                        ),
                        metric_name="liquidity_ratio",
                        metric_value=round(liquidity, 4),
                        confidence=EvidenceConfidence.MEDIUM,
                        evidence=(
                            metric_evidence(
                                current,
                                entity_type=AnalysisSubjectType.COMPANY,
                                entity_id=company.id,
                                field="liquidity_ratio",
                                value=round(liquidity, 4),
                                inputs={
                                    "cash": company.cash,
                                    "expense_magnitude": expense_magnitude,
                                },
                            ),
                        ),
                        limitations=(ACCOUNTING_LIMITATION,),
                        recommendation_code="review_liquidity",
                    ),
                )
        if company.cash < 0 and company.loan > 0:
            add_result(
                findings,
                recommendations,
                make_finding(
                    snapshot=current,
                    analysis_type=self.analysis_type,
                    code="negative_cash_with_debt",
                    entity_ids=(company.id,),
                    kind=FindingKind.OBSERVED_FACT,
                    severity=FindingSeverity.CRITICAL,
                    title="Negative cash with outstanding debt",
                    summary=f"Cash is {company.cash} while the loan balance is {company.loan}.",
                    metric_name="cash",
                    metric_value=company.cash,
                    confidence=confidence,
                    evidence=(
                        field_evidence(
                            current,
                            entity_type=AnalysisSubjectType.COMPANY,
                            entity_id=company.id,
                            field="cash",
                            value=company.cash,
                        ),
                        field_evidence(
                            current,
                            entity_type=AnalysisSubjectType.COMPANY,
                            entity_id=company.id,
                            field="loan",
                            value=company.loan,
                        ),
                    ),
                    limitations=("This does not predict bankruptcy timing.",),
                    recommendation_code="review_cash_and_debt",
                ),
            )
        if company.company_value is not None:
            leverage = company.loan / max(company.company_value, 1)
            if leverage >= 0.5:
                severity = FindingSeverity.WARNING if leverage >= 1 else FindingSeverity.OPPORTUNITY
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="high_leverage",
                        entity_ids=(company.id,),
                        kind=FindingKind.INFERRED_FINDING,
                        severity=severity,
                        title="Elevated debt relative to company value",
                        summary=f"Loan is {leverage:.1%} of observed company value.",
                        metric_name="debt_to_company_value",
                        metric_value=round(leverage, 4),
                        confidence=EvidenceConfidence.MEDIUM,
                        evidence=(
                            metric_evidence(
                                current,
                                entity_type=AnalysisSubjectType.COMPANY,
                                entity_id=company.id,
                                field="debt_to_company_value",
                                value=round(leverage, 4),
                                inputs={
                                    "loan": company.loan,
                                    "company_value": company.company_value,
                                },
                            ),
                        ),
                        limitations=("Company value is not a liquidation valuation.",),
                        recommendation_code="review_leverage",
                    ),
                )
        owned = [item for item in current.vehicles if item.owner_id == company.id]
        if len(owned) >= 4:
            negative = sum(item.profit_last_year < 0 for item in owned)
            share = negative / len(owned)
            if share >= 0.25:
                severity = FindingSeverity.CRITICAL if share >= 0.5 else FindingSeverity.WARNING
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="unprofitable_fleet_share",
                        entity_ids=(company.id,),
                        kind=FindingKind.INFERRED_FINDING,
                        severity=severity,
                        title="Large unprofitable fleet share",
                        summary=(
                            f"{negative} of {len(owned)} vehicles lost money last year "
                            f"({share:.1%})."
                        ),
                        metric_name="negative_profit_share",
                        metric_value=round(share, 4),
                        confidence=EvidenceConfidence.MEDIUM,
                        evidence=(
                            metric_evidence(
                                current,
                                entity_type=AnalysisSubjectType.COMPANY,
                                entity_id=company.id,
                                field="negative_profit_share",
                                value=round(share, 4),
                                inputs={"negative_vehicles": negative, "fleet_size": len(owned)},
                            ),
                        ),
                        limitations=(
                            "New, redirected, or deliberately subsidized vehicles can be false "
                            "positives.",
                        ),
                        recommendation_code="inspect_negative_vehicles",
                    ),
                )
            counts: dict[str, int] = {}
            for vehicle in owned:
                counts[vehicle.type] = counts.get(vehicle.type, 0) + 1
            largest_type, largest_count = min(counts.items(), key=lambda item: (-item[1], item[0]))
            concentration = largest_count / len(owned)
            if concentration >= 0.75:
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="fleet_concentration",
                        entity_ids=(company.id,),
                        kind=FindingKind.INFERRED_FINDING,
                        severity=FindingSeverity.OPPORTUNITY,
                        title="Fleet concentrated in one vehicle type",
                        summary=(
                            f"{largest_type} vehicles represent {concentration:.1%} of the fleet."
                        ),
                        metric_name="largest_vehicle_type_share",
                        metric_value=round(concentration, 4),
                        confidence=EvidenceConfidence.MEDIUM,
                        evidence=(
                            metric_evidence(
                                current,
                                entity_type=AnalysisSubjectType.COMPANY,
                                entity_id=company.id,
                                field="largest_vehicle_type_share",
                                value=round(concentration, 4),
                                inputs={
                                    "vehicle_type": largest_type,
                                    "count": largest_count,
                                    "fleet_size": len(owned),
                                },
                            ),
                        ),
                        limitations=("Concentration is not inherently harmful.",),
                        recommendation_code="review_fleet_concentration",
                    ),
                )
        if previous is not None:
            cash_change = company.cash - previous.cash
            if (
                cash_change < 0
                and percentage_change(company.cash, previous.cash) >= 0.1
                and abs(cash_change) >= 100_000
            ):
                add_result(
                    findings,
                    recommendations,
                    make_finding(
                        snapshot=current,
                        analysis_type=self.analysis_type,
                        code="material_cash_decline",
                        entity_ids=(company.id,),
                        kind=FindingKind.OBSERVED_FACT,
                        severity=FindingSeverity.WARNING,
                        title="Material cash decline",
                        summary=(
                            f"Cash declined by {abs(cash_change)} since the comparison snapshot."
                        ),
                        metric_name="cash_change",
                        metric_value=cash_change,
                        comparison_value=previous.cash,
                        confidence=confidence,
                        evidence=(
                            field_evidence(
                                current,
                                entity_type=AnalysisSubjectType.COMPANY,
                                entity_id=company.id,
                                field="cash",
                                value=company.cash,
                                comparison=comparison,
                                comparison_value=previous.cash,
                            ),
                        ),
                        limitations=(
                            "Currency thresholds vary with inflation and economy settings.",
                        ),
                        recommendation_code="inspect_cash_decline",
                    ),
                )
        findings.sort(key=lambda item: (-_severity(item.severity), item.finding_id))
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED,
            answer=f"Company health produced {len(findings)} evidence-backed findings.",
            findings=tuple(findings),
            recommendations=tuple(recommendations),
            limitations=("Infrastructure and maintenance expenses are not exposed separately.",),
        )


class FinancialSummaryAnalyzer:
    analysis_type = AnalysisType.FINANCIAL_SUMMARY

    def analyze(
        self,
        request: AnalysisRequest,
        current: WorldSnapshot,
        comparison: WorldSnapshot | None,
    ) -> AnalyzerResult:
        del request
        company = observer_company(current)
        previous = _matching_company(comparison, company.id)
        fields = ("cash", "loan", "company_value", "income", "expenses")
        findings: list[AnalysisFinding] = []
        for field in fields:
            value = getattr(company, field)
            if value is None:
                continue
            previous_value = None if previous is None else getattr(previous, field)
            finding, _ = make_finding(
                snapshot=current,
                analysis_type=self.analysis_type,
                code=f"observed_{field}",
                entity_ids=(company.id,),
                kind=FindingKind.OBSERVED_FACT,
                severity=FindingSeverity.INFORMATIONAL,
                title=f"Observed {field.replace('_', ' ')}",
                summary=f"{field.replace('_', ' ').title()} is {value}.",
                metric_name=field,
                metric_value=value,
                comparison_value=previous_value,
                confidence=EvidenceConfidence.HIGH,
                evidence=(
                    field_evidence(
                        current,
                        entity_type=AnalysisSubjectType.COMPANY,
                        entity_id=company.id,
                        field=field,
                        value=value,
                        comparison=comparison if previous_value is not None else None,
                        comparison_value=previous_value,
                    ),
                ),
            )
            findings.append(finding)
        if company.income is not None and company.expenses is not None:
            net = company.income + company.expenses
            finding, _ = make_finding(
                snapshot=current,
                analysis_type=self.analysis_type,
                code="net_operating_result",
                entity_ids=(company.id,),
                kind=FindingKind.OBSERVED_FACT,
                severity=FindingSeverity.WARNING if net < 0 else FindingSeverity.INFORMATIONAL,
                title="Net operating result",
                summary=f"Observed income plus expenses is {net}.",
                metric_name="net_operating_result",
                metric_value=net,
                confidence=EvidenceConfidence.HIGH,
                evidence=(
                    metric_evidence(
                        current,
                        entity_type=AnalysisSubjectType.COMPANY,
                        entity_id=company.id,
                        field="net_operating_result",
                        value=net,
                        inputs={"income": company.income, "expenses": company.expenses},
                    ),
                ),
                limitations=(ACCOUNTING_LIMITATION,),
            )
            findings.append(finding)
        missing = tuple(field for field in fields if getattr(company, field) is None)
        limitations = tuple(
            f"{field.replace('_', ' ').title()} is unavailable." for field in missing
        )
        return AnalyzerResult(
            status=AnalysisStatus.COMPLETED,
            answer=(
                f"Financial summary for {company.name} contains {len(findings)} observed metrics."
            ),
            findings=tuple(findings),
            limitations=limitations,
        )


def _matching_company(snapshot: WorldSnapshot | None, identifier: str) -> Company | None:
    if snapshot is None:
        return None
    return next((item for item in snapshot.companies if item.id == identifier), None)


def _severity(severity: FindingSeverity) -> int:
    return {
        FindingSeverity.INFORMATIONAL: 0,
        FindingSeverity.OPPORTUNITY: 1,
        FindingSeverity.WARNING: 2,
        FindingSeverity.CRITICAL: 3,
    }[severity]
