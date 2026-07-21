"""Validate, execute once, re-observe, and verify Rail Route controls."""

import time
from collections.abc import Callable

from sim_pilot.rail_route.errors import (
    RailRouteDiscoveryError,
    RailRouteObservationError,
    RailRouteVerificationError,
)
from sim_pilot.rail_route.macos import activate_rail_route, send_space_key
from sim_pilot.rail_route.models import (
    RailRouteAction,
    RailRouteControlResult,
    RailRouteIntent,
    RailRouteObservation,
    RailRouteScreenState,
)
from sim_pilot.rail_route.screen import RailRouteScreenObserver

ObservationFunction = Callable[[], RailRouteObservation]
InputFunction = Callable[[], None]


class RailRouteController:
    """Small verified control surface for the live macOS game."""

    def __init__(
        self,
        observe: ObservationFunction | None = None,
        send_pause_toggle: InputFunction | None = None,
        *,
        verification_attempts: int = 5,
        verification_interval_seconds: float = 0.2,
    ) -> None:
        observer = RailRouteScreenObserver()
        self._observe = observe or observer.observe
        self._send_pause_toggle = send_pause_toggle or _send_space
        self._verification_attempts = verification_attempts
        self._verification_interval_seconds = verification_interval_seconds

    def observe(self) -> RailRouteObservation:
        return self._observe()

    def execute(self, intent: RailRouteIntent) -> RailRouteControlResult:
        before = self._observe()
        if not before.installation.supported:
            raise RailRouteDiscoveryError(before.installation.compatibility_reason)
        if intent.action is RailRouteAction.STATUS:
            return RailRouteControlResult(
                intent=intent,
                before=before,
                after=before,
                input_sent=False,
                verified=True,
                message=f"Rail Route is {before.screen_state.value}.",
            )

        expected = (
            RailRouteScreenState.PAUSED
            if intent.action is RailRouteAction.PAUSE
            else RailRouteScreenState.RUNNING
        )
        if before.screen_state is expected:
            return RailRouteControlResult(
                intent=intent,
                before=before,
                after=before,
                input_sent=False,
                verified=True,
                message=f"Rail Route is already {expected.value}.",
            )
        allowed_before = (
            {RailRouteScreenState.RUNNING, RailRouteScreenState.OTHER_SPEED}
            if intent.action is RailRouteAction.PAUSE
            else {RailRouteScreenState.PAUSED}
        )
        if before.screen_state not in allowed_before:
            raise RailRouteObservationError(
                f"cannot {intent.action.value} from screen state {before.screen_state.value}; "
                "return to an active single-player game view"
            )

        self._send_pause_toggle()
        after = before
        for _ in range(self._verification_attempts):
            time.sleep(self._verification_interval_seconds)
            after = self._observe()
            if after.screen_state is expected:
                return RailRouteControlResult(
                    intent=intent,
                    before=before,
                    after=after,
                    input_sent=True,
                    verified=True,
                    message=f"Rail Route {expected.value}; effect verified from the game UI.",
                )
        raise RailRouteVerificationError(
            f"sent {intent.action.value} once but observed {after.screen_state.value}; "
            "no retry was attempted"
        )


def _send_space() -> None:
    try:
        activate_rail_route()
        send_space_key()
    except RuntimeError as error:
        raise RailRouteObservationError(str(error)) from error
