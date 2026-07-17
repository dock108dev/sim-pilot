"""Explicitly enabled, non-mutating OpenTTD integration acceptance test."""

import asyncio
import os

import pytest

from sim_pilot.adapters.openttd import OpenTTDReadOnlyAdapter
from sim_pilot.domain import Action
from sim_pilot.openttd import OpenTTDAdminClient, openttd_configuration


@pytest.mark.live
def test_live_openttd_two_observations_and_read_only_rejection() -> None:
    if os.getenv("SIM_PILOT_LIVE_OPENTTD") != "1":
        pytest.skip("set SIM_PILOT_LIVE_OPENTTD=1 with local OpenTTD 15.3 to run")

    async def scenario() -> None:
        adapter = OpenTTDReadOnlyAdapter(OpenTTDAdminClient(openttd_configuration()))
        await adapter.initialize()
        try:
            first = await adapter.observe()
            await asyncio.sleep(openttd_configuration().polling_interval_seconds)
            second = await adapter.observe()
            assert second.sequence == first.sequence + 1
            assert second.tick >= first.tick
            assert not (await adapter.validate(Action(type="pause", expected_effect="pause"))).valid
        finally:
            await adapter.shutdown()

    asyncio.run(scenario())
