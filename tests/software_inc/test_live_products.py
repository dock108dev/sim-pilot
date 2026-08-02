"""Opt-in Prompt 7 Atlas preflight and save non-mutation acceptance."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal
from pathlib import Path

import pytest

from sim_pilot.software_inc.bridge import software_inc_bridge_client
from sim_pilot.software_inc.bridge.proof import save_fingerprint
from sim_pilot.software_inc.products import ProductWorkflowStore, start_atlas

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_SOFTWARE_INC_PRODUCTS") != "1",
    reason=(
        "set SIM_PILOT_LIVE_SOFTWARE_INC_PRODUCTS=1 for a paused disposable company "
        "without Atlas; reversible design setup may occur but no product commitment is sent"
    ),
)
def test_live_atlas_preflight_and_non_mutation(tmp_path: Path) -> None:
    async def scenario() -> None:
        reserve = Decimal(os.environ.get("SIM_PILOT_SOFTWARE_INC_PRODUCT_RESERVE", "50000"))
        save_before = save_fingerprint()
        client = software_inc_bridge_client()
        try:
            capabilities = await client.connect()
        finally:
            await client.close()
        assert capabilities.gameplay_actions == ()

        result = await start_atlas(
            minimum_cash_reserve=reserve,
            approval_provider=None,
            store=ProductWorkflowStore(tmp_path / "products.sqlite3"),
        )
        save_after = save_fingerprint()

        assert result.partial
        assert save_after == save_before
        assert 0 <= result.gestures_sent <= 24
        if result.recommendation is not None and result.recommendation.recommended:
            assert result.workflow is not None
            assert result.workflow.pending_approval is not None
            assert result.workflow.pending_approval.approved is None
        else:
            assert result.workflow is None
            assert result.recommendation is not None
            assert result.recommendation.reasons

    asyncio.run(scenario())
