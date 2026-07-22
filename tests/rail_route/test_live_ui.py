"""Opt-in live Test Yard UI observation and route acceptance."""

import asyncio
import os

import pytest

from sim_pilot.rail_route.intent import parse_control_intent
from sim_pilot.rail_route.ui.controller import execute_set_route_ui
from sim_pilot.rail_route.ui.observer import RailRouteUIObserver

pytestmark = pytest.mark.live


def test_live_ui_dry_run() -> None:
    if os.environ.get("SIM_PILOT_LIVE_RAIL_ROUTE_UI") != "1":
        pytest.skip("set SIM_PILOT_LIVE_RAIL_ROUTE_UI=1 for Test Yard UI observation")
    capabilities = asyncio.run(RailRouteUIObserver().capabilities())
    assert capabilities.actions == ("set_route_ui",)
    assert capabilities.mutation_allowed
    result = asyncio.run(
        execute_set_route_ui(
            parse_control_intent("set a route from SIG-W-IN to SIG-C-W"), dry_run=True
        )
    )
    assert result.verified
    assert result.gestures_sent == 0


def test_live_ui_route_action() -> None:
    if os.environ.get("SIM_PILOT_LIVE_RAIL_ROUTE_UI_ACTION") != "1":
        pytest.skip("set SIM_PILOT_LIVE_RAIL_ROUTE_UI_ACTION=1 for the disposable route action")
    result = asyncio.run(
        execute_set_route_ui(parse_control_intent("set a route from SIG-W-IN to SIG-C-W"))
    )
    assert result.verified
    assert result.gestures_sent == 2
