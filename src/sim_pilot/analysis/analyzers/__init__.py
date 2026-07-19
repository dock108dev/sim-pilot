"""Deterministic analyzers over canonical world snapshots."""

from sim_pilot.analysis.analyzers.base import Analyzer, AnalyzerResult
from sim_pilot.analysis.analyzers.changes import (
    AnomalyDetectionAnalyzer,
    EntitySummaryAnalyzer,
    PriorityReviewAnalyzer,
    WorldChangesAnalyzer,
)
from sim_pilot.analysis.analyzers.coverage import (
    IndustryOpportunitiesAnalyzer,
    ServiceCoverageAnalyzer,
    TownCoverageAnalyzer,
)
from sim_pilot.analysis.analyzers.financial import CompanyHealthAnalyzer, FinancialSummaryAnalyzer
from sim_pilot.analysis.analyzers.network import (
    RoutePerformanceAnalyzer,
    StationPerformanceAnalyzer,
)
from sim_pilot.analysis.analyzers.vehicles import FleetSummaryAnalyzer, VehiclePerformanceAnalyzer

__all__ = [
    "Analyzer",
    "AnalyzerResult",
    "AnomalyDetectionAnalyzer",
    "CompanyHealthAnalyzer",
    "FinancialSummaryAnalyzer",
    "FleetSummaryAnalyzer",
    "IndustryOpportunitiesAnalyzer",
    "EntitySummaryAnalyzer",
    "PriorityReviewAnalyzer",
    "RoutePerformanceAnalyzer",
    "ServiceCoverageAnalyzer",
    "StationPerformanceAnalyzer",
    "TownCoverageAnalyzer",
    "VehiclePerformanceAnalyzer",
    "WorldChangesAnalyzer",
]
