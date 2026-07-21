"""Opt-in live proof against the running disposable Rail Route game."""

import os

import pytest

from sim_pilot.rail_route import RailRouteController, parse_control_intent
from sim_pilot.rail_route.models import RailRouteScreenState

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.getenv("SIM_PILOT_LIVE_RAIL_ROUTE") != "1",
    reason="set SIM_PILOT_LIVE_RAIL_ROUTE=1 for verified local Rail Route control",
)
def test_live_pause_resume_and_restore_initial_state() -> None:
    controller = RailRouteController()
    initial = controller.observe()
    if initial.screen_state not in {RailRouteScreenState.PAUSED, RailRouteScreenState.RUNNING}:
        pytest.skip("open an active single-player Rail Route game at pause or normal speed")

    first_instruction, restore_instruction = (
        ("pause the game", "resume the game")
        if initial.screen_state is RailRouteScreenState.RUNNING
        else ("resume the game", "pause the game")
    )
    first = controller.execute(parse_control_intent(first_instruction))
    restored = controller.execute(parse_control_intent(restore_instruction))

    assert first.input_sent and first.verified
    assert restored.input_sent and restored.verified
    assert restored.after.screen_state is initial.screen_state
