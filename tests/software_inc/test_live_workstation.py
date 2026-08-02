"""Opt-in destructive acceptance for Prompt 5B on a disposable company."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest

from sim_pilot.software_inc.bridge import software_inc_bridge_client
from sim_pilot.software_inc.ui import (
    SoftwareIncUIObserver,
    execute_workstation_intent,
    parse_workstation_intent,
)

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_SOFTWARE_INC_WORKSTATION") != "1",
    reason=(
        "set SIM_PILOT_LIVE_SOFTWARE_INC_WORKSTATION=1 only for an explicitly approved "
        "disposable-company workstation purchase"
    ),
)
def test_live_exact_workstation_purchase_and_room_assignment() -> None:
    async def scenario() -> None:
        team = os.environ.get("SIM_PILOT_SOFTWARE_INC_WORKSTATION_TEAM", "Core")
        reserve = Decimal(os.environ.get("SIM_PILOT_SOFTWARE_INC_WORKSTATION_RESERVE", "0"))
        client = software_inc_bridge_client()
        try:
            capabilities = await client.connect()
        finally:
            await client.close()
        assert capabilities.gameplay_actions == ()

        intent = parse_workstation_intent(
            f"prepare one workstation for {team} while keeping ${reserve} in reserve"
        )
        preview = await execute_workstation_intent(intent, dry_run=True)
        assert preview.gestures_sent == 0
        assert preview.plan.projected_cash_after >= reserve

        result = await execute_workstation_intent(
            intent,
            approval_provider=lambda _plan: True,
        )
        final = (await SoftwareIncUIObserver().observe()).observation

        assert result.verified and not result.partial
        if result.plan.assign_room_to_team or result.plan.line_items:
            assert result.approval is not None and result.approval.approved
        else:
            assert result.approval is None
            assert result.gestures_sent == 0
        assert final.paused
        assert result.after.semantic_after.game_session_id == final.semantic_after.game_session_id

    asyncio.run(scenario())
