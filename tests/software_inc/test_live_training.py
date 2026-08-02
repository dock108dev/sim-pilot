"""Opt-in live Prompt 6B observation, navigation, and non-mutation acceptance."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from pathlib import Path

import pytest

from sim_pilot.software_inc.bridge import software_inc_bridge_client
from sim_pilot.software_inc.bridge.proof import save_fingerprint
from sim_pilot.software_inc.training import recommend_training, start_training
from sim_pilot.software_inc.training.store import TrainingWorkflowStore

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_SOFTWARE_INC_TRAINING") != "1",
    reason=(
        "set SIM_PILOT_LIVE_SOFTWARE_INC_TRAINING=1 for a paused disposable company "
        "with an idle exact team and at least one employee"
    ),
)
def test_live_training_recommendation_navigation_and_non_mutation(tmp_path: Path) -> None:
    async def scenario() -> None:
        team = os.environ.get("SIM_PILOT_SOFTWARE_INC_TRAINING_TEAM", "Core")
        reserve = Decimal(os.environ.get("SIM_PILOT_SOFTWARE_INC_TRAINING_RESERVE", "0"))
        save_before = save_fingerprint()
        client = software_inc_bridge_client()
        try:
            capabilities = await client.connect()
            snapshot = await client.request_full_snapshot()
        finally:
            await client.close()

        recommendation = recommend_training(
            snapshot,
            team_name=team,
            minimum_cash_reserve=reserve,
        )
        assert capabilities.gameplay_actions == ()
        if recommendation.recommended is None:
            assert recommendation.rejection_reasons
            assert save_fingerprint() == save_before
            return
        assert len(recommendation.alternatives) <= 2

        result = await start_training(
            recommendation,
            approval_provider=None,
            store=TrainingWorkflowStore(tmp_path / "training.sqlite3"),
        )
        save_after = save_fingerprint()

        assert result.partial and not result.verified
        assert result.workflow is not None
        assert result.workflow.pending_approval is not None
        assert result.workflow.pending_approval.approved is None
        assert "Educate" in result.message
        assert 0 <= result.gestures_sent <= 8
        assert save_after == save_before

    asyncio.run(scenario())
