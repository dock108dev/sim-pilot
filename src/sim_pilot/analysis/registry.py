"""Explicit analyzer registration with fail-closed lookup."""

from sim_pilot.analysis.analyzers import (
    Analyzer,
    AnomalyDetectionAnalyzer,
    CompanyHealthAnalyzer,
    EntitySummaryAnalyzer,
    FinancialSummaryAnalyzer,
    FleetSummaryAnalyzer,
    IndustryOpportunitiesAnalyzer,
    PriorityReviewAnalyzer,
    RoutePerformanceAnalyzer,
    ServiceCoverageAnalyzer,
    StationPerformanceAnalyzer,
    TownCoverageAnalyzer,
    VehiclePerformanceAnalyzer,
    WorldChangesAnalyzer,
)
from sim_pilot.analysis.contracts import AnalysisType
from sim_pilot.analysis.errors import AnalyzerRegistrationError


class AnalyzerRegistry:
    def __init__(self, analyzers: tuple[Analyzer, ...] = ()) -> None:
        self._analyzers: dict[AnalysisType, Analyzer] = {}
        for analyzer in analyzers:
            self.register(analyzer)

    def register(self, analyzer: Analyzer) -> None:
        if analyzer.analysis_type in self._analyzers:
            raise AnalyzerRegistrationError(
                f"duplicate analyzer registration: {analyzer.analysis_type.value}"
            )
        self._analyzers[analyzer.analysis_type] = analyzer

    def get(self, analysis_type: AnalysisType) -> Analyzer:
        try:
            return self._analyzers[analysis_type]
        except KeyError as error:
            raise AnalyzerRegistrationError(
                f"no analyzer registered for {analysis_type.value}"
            ) from error

    @property
    def registered_types(self) -> tuple[AnalysisType, ...]:
        return tuple(sorted(self._analyzers, key=lambda value: value.value))


def default_analyzer_registry() -> AnalyzerRegistry:
    return AnalyzerRegistry(
        (
            CompanyHealthAnalyzer(),
            FinancialSummaryAnalyzer(),
            VehiclePerformanceAnalyzer(),
            StationPerformanceAnalyzer(),
            RoutePerformanceAnalyzer(),
            ServiceCoverageAnalyzer(),
            IndustryOpportunitiesAnalyzer(),
            TownCoverageAnalyzer(),
            FleetSummaryAnalyzer(),
            WorldChangesAnalyzer(),
            AnomalyDetectionAnalyzer(),
            PriorityReviewAnalyzer(),
            EntitySummaryAnalyzer(),
        )
    )
