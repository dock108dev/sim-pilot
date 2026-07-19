from sim_pilot.analysis.analyzers.financial import CompanyHealthAnalyzer, FinancialSummaryAnalyzer
from sim_pilot.analysis.contracts import AnalysisRequest, AnalysisStatus, AnalysisType
from sim_pilot.domain.world import Company, Vehicle, VehicleCounts
from tests.analysis.helpers import snapshot


def vehicle(identifier: str, profit: int, *, vehicle_type: str = "road") -> Vehicle:
    return Vehicle(
        id=identifier,
        type=vehicle_type,
        name=identifier,
        age_days=100,
        profit_this_year=profit,
        profit_last_year=profit,
        running_state="running",
        coordinates=None,
        in_depot=False,
        owner_id="company-1",
    )


def test_company_health_thresholds_and_evidence() -> None:
    company = Company(
        id="company-1",
        name="Loss Line",
        cash=50_000,
        loan=600_000,
        company_value=500_000,
        income=100_000,
        expenses=-200_000,
        vehicle_counts=VehicleCounts(road=4),
    )
    world = snapshot(
        company=company,
        vehicles=tuple(vehicle(str(index), -1000 if index < 2 else 1000) for index in range(4)),
    )

    result = CompanyHealthAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.COMPANY_HEALTH, question="Why losses?"),
        world,
        None,
    )

    codes = {item.finding_code for item in result.findings}
    assert {
        "negative_operating_result",
        "low_liquidity_reserve",
        "high_leverage",
        "unprofitable_fleet_share",
        "fleet_concentration",
    }.issubset(codes)
    assert all(item.evidence for item in result.findings)
    assert all(not item.executable for item in result.recommendations)


def test_company_health_boundaries_do_not_trigger_below_thresholds() -> None:
    company = Company(
        id="company-1",
        name="Stable Line",
        cash=200_000,
        loan=49_999,
        company_value=100_000,
        income=200_000,
        expenses=-100_000,
    )
    vehicles = (
        vehicle("1", -1),
        vehicle("2", 1, vehicle_type="rail"),
        vehicle("3", 1, vehicle_type="air"),
        vehicle("4", 1, vehicle_type="water"),
    )

    result = CompanyHealthAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.COMPANY_HEALTH, question="Health"),
        snapshot(company=company, vehicles=vehicles),
        None,
    )

    codes = {item.finding_code for item in result.findings}
    assert "high_leverage" not in codes
    assert "unprofitable_fleet_share" in codes
    assert "fleet_concentration" not in codes


def test_financial_summary_discloses_missing_optional_fields() -> None:
    result = FinancialSummaryAnalyzer().analyze(
        AnalysisRequest(analysis_type=AnalysisType.FINANCIAL_SUMMARY, question="Finances"),
        snapshot(),
        None,
    )

    assert result.status is AnalysisStatus.COMPLETED
    assert {item.metric_name for item in result.findings} == {"cash", "loan"}
    assert "Company Value is unavailable." in result.limitations
