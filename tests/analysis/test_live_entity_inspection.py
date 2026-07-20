import asyncio
import os

import pytest

from sim_pilot.analysis.contracts import (
    AnalysisRequest,
    AnalysisType,
    RankingDirection,
    RankingMetric,
    RankingRequest,
)
from sim_pilot.analysis.entity_inspection import (
    InspectionResultStatus,
    evaluate_unsupported_inspection,
    resolve_inspection_action,
)
from sim_pilot.analysis.registry import default_analyzer_registry
from sim_pilot.analysis.service import AnalysisService
from sim_pilot.analysis.session import AnalysisSessionRecord
from sim_pilot.cli import _analysis_snapshot  # pyright: ignore[reportPrivateUsage]


@pytest.mark.live
def test_live_bridge_reports_entity_inspection_unsupported_without_writes() -> None:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD_INSPECTION") != "1":
        pytest.skip("set SIM_PILOT_LIVE_OPENTTD_INSPECTION=1 for Phase 10A discovery")
    assert os.getenv("SIM_PILOT_OPENTTD_ALLOW_WRITES", "0") == "0"
    assert os.getenv("SIM_PILOT_OPENTTD_GS_ALLOW_WRITES", "0") == "0"

    acquired = asyncio.run(_analysis_snapshot(None, True))
    verification = acquired.verification
    assert verification is not None
    assert "focus_named_entity" not in acquired.bridge_supported_actions
    response = (
        AnalysisService(default_analyzer_registry())
        .analyze(
            AnalysisRequest(
                analysis_type=AnalysisType.VEHICLE_PERFORMANCE,
                question="Which vehicle lost the most money last year?",
                ranking=RankingRequest(
                    metric=RankingMetric.PROFIT_LAST_YEAR,
                    direction=RankingDirection.ASCENDING,
                ),
            ),
            acquired.snapshot,
        )
        .model_copy(update={"snapshot_metadata": acquired.metadata()})
    )
    record = AnalysisSessionRecord(
        analysis_id=f"analysis:{'b' * 20}",
        response=response,
        snapshot=acquired.snapshot,
    )
    action = resolve_inspection_action(record, response.findings[0].finding_id)

    result = evaluate_unsupported_inspection(
        action,
        acquired.snapshot,
        bridge_company_context=verification.identity.bridge_company_context,
        supported_actions=acquired.bridge_supported_actions,
    )

    assert result.status is InspectionResultStatus.UNSUPPORTED
    assert result.executed is False
    assert result.economic_mutation is False
