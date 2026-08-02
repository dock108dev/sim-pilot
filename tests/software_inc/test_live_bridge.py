import asyncio
import os

import pytest

from sim_pilot.software_inc.bridge import prove_read_only_bridge, software_inc_bridge_client


@pytest.mark.live
@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_SOFTWARE_INC_BRIDGE") != "1",
    reason="set SIM_PILOT_LIVE_SOFTWARE_INC_BRIDGE=1 in a paused disposable company",
)
def test_live_bridge_is_read_only_and_semantically_stable() -> None:
    asyncio.run(_exercise_live_bridge())


async def _exercise_live_bridge() -> None:
    client = software_inc_bridge_client()
    try:
        capabilities = await client.connect()
        snapshot = await client.request_full_snapshot()
    finally:
        await client.close()

    assert capabilities.gameplay_actions == ()
    assert snapshot.game_id == "software-inc"
    assert {item.coverage.surface for item in snapshot.surfaces} == {
        "applicants",
        "build_catalog",
        "build_ui",
        "company",
        "contract_market",
        "contract_results",
        "contract_ui",
        "education",
        "education_ui",
        "employees",
        "finances",
        "game_state",
        "infrastructure",
        "office_ui",
        "offices",
        "products",
        "staffing_ui",
        "teams",
        "work_items",
    }
    proof = await prove_read_only_bridge()
    assert proof.passed, proof.reasons
