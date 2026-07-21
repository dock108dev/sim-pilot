"""Deterministic Rail Route intent and control coverage."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from sim_pilot.rail_route.controller import RailRouteController
from sim_pilot.rail_route.errors import (
    RailRouteIntentError,
    RailRouteObservationError,
    RailRouteVerificationError,
)
from sim_pilot.rail_route.intent import parse_control_intent
from sim_pilot.rail_route.models import (
    RailRouteAction,
    RailRouteInstallation,
    RailRouteObservation,
    RailRouteScreenState,
)
from sim_pilot.rail_route.screen import classify_speed_state


def installation(*, supported: bool = True) -> RailRouteInstallation:
    return RailRouteInstallation(
        app_path=Path("/Applications/Rail Route.app"),
        executable_path=Path("/Applications/Rail Route.app/Contents/MacOS/Rail Route"),
        version="2.3.24",
        steam_app_id="1124180",
        steam_build_id="22547955",
        process_id=123,
        running=True,
        accessibility_enabled=True,
        supported=supported,
        compatibility_reason="compatible" if supported else "incompatible test fixture",
    )


def observation(state: RailRouteScreenState) -> RailRouteObservation:
    scores = {
        RailRouteScreenState.PAUSED: (160, 0, 0),
        RailRouteScreenState.RUNNING: (0, 130, 0),
        RailRouteScreenState.OTHER_SPEED: (0, 0, 130),
    }.get(state, (0, 0, 0))
    return RailRouteObservation(
        observed_at=datetime.now(UTC),
        installation=installation(),
        screen_state=state,
        screen_width=1920,
        screen_height=1080,
        pause_score=scores[0],
        normal_speed_score=scores[1],
        accelerated_speed_score=scores[2],
    )


@pytest.mark.parametrize(
    ("instruction", "action"),
    [
        ("What is the game doing?", RailRouteAction.STATUS),
        ("Pause the game", RailRouteAction.PAUSE),
        ("please stop for a moment", RailRouteAction.PAUSE),
        ("Resume the game", RailRouteAction.RESUME),
        ("continue playing", RailRouteAction.RESUME),
    ],
)
def test_parse_supported_plain_english(instruction: str, action: RailRouteAction) -> None:
    assert parse_control_intent(instruction).action is action


def test_parser_rejects_route_control_until_semantic_verification_exists() -> None:
    with pytest.raises(RailRouteIntentError, match="route-setting is not enabled"):
        parse_control_intent("Route train 12 to platform 2")


def test_parser_rejects_conflicting_actions() -> None:
    with pytest.raises(RailRouteIntentError, match="conflicting"):
        parse_control_intent("pause and then resume")


def test_pause_sends_one_input_and_verifies_postcondition() -> None:
    observations = iter(
        [observation(RailRouteScreenState.RUNNING), observation(RailRouteScreenState.PAUSED)]
    )
    inputs: list[str] = []
    controller = RailRouteController(
        observe=lambda: next(observations),
        send_pause_toggle=lambda: inputs.append("space"),
        verification_interval_seconds=0,
    )

    result = controller.execute(parse_control_intent("pause the game"))

    assert result.verified
    assert result.input_sent
    assert result.after.screen_state is RailRouteScreenState.PAUSED
    assert inputs == ["space"]


def test_already_satisfied_intent_sends_no_input() -> None:
    inputs: list[str] = []
    controller = RailRouteController(
        observe=lambda: observation(RailRouteScreenState.PAUSED),
        send_pause_toggle=lambda: inputs.append("space"),
        verification_interval_seconds=0,
    )

    result = controller.execute(parse_control_intent("pause"))

    assert result.verified
    assert not result.input_sent
    assert inputs == []


def test_non_gameplay_screen_fails_before_input() -> None:
    inputs: list[str] = []
    controller = RailRouteController(
        observe=lambda: observation(RailRouteScreenState.NOT_GAMEPLAY),
        send_pause_toggle=lambda: inputs.append("space"),
        verification_interval_seconds=0,
    )

    with pytest.raises(RailRouteObservationError, match="active single-player game view"):
        controller.execute(parse_control_intent("pause"))
    assert inputs == []


def test_failed_verification_does_not_retry_input() -> None:
    observations = iter(
        [
            observation(RailRouteScreenState.RUNNING),
            observation(RailRouteScreenState.RUNNING),
            observation(RailRouteScreenState.RUNNING),
        ]
    )
    inputs: list[str] = []
    controller = RailRouteController(
        observe=lambda: next(observations),
        send_pause_toggle=lambda: inputs.append("space"),
        verification_attempts=2,
        verification_interval_seconds=0,
    )

    with pytest.raises(RailRouteVerificationError, match="no retry was attempted"):
        controller.execute(parse_control_intent("pause"))
    assert inputs == ["space"]


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ((163, 0, 0), RailRouteScreenState.PAUSED),
        ((0, 136, 0), RailRouteScreenState.RUNNING),
        ((0, 0, 120), RailRouteScreenState.OTHER_SPEED),
        ((0, 0, 0), RailRouteScreenState.NOT_GAMEPLAY),
        ((100, 95, 0), RailRouteScreenState.UNKNOWN),
    ],
)
def test_screen_state_classification(
    scores: tuple[int, int, int], expected: RailRouteScreenState
) -> None:
    assert classify_speed_state(*scores) is expected
