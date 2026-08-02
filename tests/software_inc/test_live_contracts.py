"""Opt-in live Prompt 6A market, policy, and non-mutation acceptance."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest

from sim_pilot.software_inc.bridge import software_inc_bridge_client
from sim_pilot.software_inc.bridge.proof import save_fingerprint
from sim_pilot.software_inc.contracts import browse_contracts, recommend_contracts

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_SOFTWARE_INC_CONTRACTS") != "1",
    reason=(
        "set SIM_PILOT_LIVE_SOFTWARE_INC_CONTRACTS=1 for a paused disposable company "
        "with one contract-ready exact team"
    ),
)
def test_live_contract_market_recommendation_and_non_mutation() -> None:
    async def scenario() -> None:
        team = os.environ.get("SIM_PILOT_SOFTWARE_INC_CONTRACT_TEAM", "Core")
        minimum_reward = Decimal(
            os.environ.get("SIM_PILOT_SOFTWARE_INC_CONTRACT_MINIMUM_REWARD", "0")
        )
        reserve = Decimal(os.environ.get("SIM_PILOT_SOFTWARE_INC_CONTRACT_RESERVE", "0"))
        save_before = save_fingerprint()
        browse = await browse_contracts()
        assert browse.verified

        client = software_inc_bridge_client()
        try:
            capabilities = await client.connect()
            snapshot = await client.request_full_snapshot()
        finally:
            await client.close()
        recommendation = recommend_contracts(
            snapshot,
            team_name=team,
            minimum_reward=minimum_reward,
            minimum_cash_reserve=reserve,
        )
        save_after = save_fingerprint()

        assert capabilities.gameplay_actions == ()
        assert recommendation.recommended is not None, recommendation.material_unknowns
        assert len(recommendation.alternatives) <= 2
        assert save_after == save_before

    asyncio.run(scenario())
