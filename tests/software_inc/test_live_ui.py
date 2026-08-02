"""Opt-in live acceptance for the current Software Inc. Phase 3 state."""

from __future__ import annotations

import asyncio
import os

import pytest

from sim_pilot.software_inc.bridge.proof import save_fingerprint
from sim_pilot.software_inc.ui import (
    ModalState,
    SoftwareIncUIAction,
    SoftwareIncUIObserver,
    SoftwareIncUIScene,
    execute_ui_action,
)

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_SOFTWARE_INC_UI") != "1",
    reason="set SIM_PILOT_LIVE_SOFTWARE_INC_UI=1 for the bounded disposable-company UI proof",
)
def test_current_manage_teams_state_is_verified_without_input() -> None:
    async def scenario() -> None:
        save_before = save_fingerprint()
        first = (await SoftwareIncUIObserver().observe()).observation
        surfaces_before = tuple(
            surface.model_dump(mode="json") for surface in first.semantic_after.surfaces
        )
        management = await execute_ui_action(SoftwareIncUIAction.OPEN_MANAGE_TEAMS)
        save_after = save_fingerprint()

        assert first.scene is SoftwareIncUIScene.MANAGE_TEAMS
        assert first.modal_state in {ModalState.NONE, ModalState.BLOCKING}
        assert management.verified and management.gestures_sent == 0
        assert management.after.paused
        assert (
            tuple(
                surface.model_dump(mode="json")
                for surface in management.after.semantic_after.surfaces
            )
            == surfaces_before
        )
        assert save_after == save_before

    asyncio.run(scenario())
