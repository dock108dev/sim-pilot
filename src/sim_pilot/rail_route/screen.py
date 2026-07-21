"""Screen acquisition and deterministic Rail Route speed-state recognition."""

import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from PIL import Image

from sim_pilot.rail_route.discovery import RailRouteDiscovery
from sim_pilot.rail_route.errors import RailRouteObservationError
from sim_pilot.rail_route.macos import activate_rail_route
from sim_pilot.rail_route.models import RailRouteObservation, RailRouteScreenState

_YELLOW_RED_MINIMUM = 180
_YELLOW_GREEN_MINIMUM = 150
_YELLOW_BLUE_MAXIMUM = 100
_SELECTED_SCORE_MINIMUM = 35


class RailRouteScreenObserver:
    """Observe only the version-pinned fullscreen speed controls."""

    def __init__(self, discovery: RailRouteDiscovery | None = None) -> None:
        self._discovery = discovery or RailRouteDiscovery()

    def observe(self) -> RailRouteObservation:
        installation = self._discovery.inspect()
        if not installation.running:
            raise RailRouteObservationError("Rail Route is not running")
        self._activate()
        with tempfile.TemporaryDirectory(prefix="sim-pilot-rail-route-") as directory:
            screenshot = Path(directory) / "screen.png"
            completed = subprocess.run(
                ["screencapture", "-x", str(screenshot)],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode != 0 or not screenshot.is_file():
                reason = completed.stderr.strip() or "screen capture produced no image"
                raise RailRouteObservationError(f"unable to capture Rail Route: {reason}")
            with Image.open(screenshot) as image:
                rgb = image.convert("RGB")
                width, height = rgb.size
                pause_score = _yellow_score(rgb, (0.444, 0.848, 0.463, 0.887))
                normal_score = _yellow_score(rgb, (0.467, 0.848, 0.486, 0.887))
                accelerated_score = max(
                    _yellow_score(rgb, (0.490, 0.848, 0.509, 0.887)),
                    _yellow_score(rgb, (0.513, 0.848, 0.532, 0.887)),
                    _yellow_score(rgb, (0.536, 0.848, 0.555, 0.887)),
                )
        screen_state = classify_speed_state(pause_score, normal_score, accelerated_score)
        return RailRouteObservation(
            observed_at=datetime.now(UTC),
            installation=installation,
            screen_state=screen_state,
            screen_width=width,
            screen_height=height,
            pause_score=pause_score,
            normal_speed_score=normal_score,
            accelerated_speed_score=accelerated_score,
        )

    @staticmethod
    def _activate() -> None:
        try:
            activate_rail_route()
        except RuntimeError as error:
            raise RailRouteObservationError(str(error)) from error


def _yellow_score(image: Image.Image, bounds: tuple[float, float, float, float]) -> int:
    width, height = image.size
    left, top, right, bottom = bounds
    crop = image.crop(
        (
            round(width * left),
            round(height * top),
            round(width * right),
            round(height * bottom),
        )
    )
    score = 0
    for pixel in crop.get_flattened_data():
        red, green, blue = cast("tuple[int, int, int]", pixel)
        if (
            red >= _YELLOW_RED_MINIMUM
            and green >= _YELLOW_GREEN_MINIMUM
            and blue <= _YELLOW_BLUE_MAXIMUM
        ):
            score += 1
    return score


def classify_speed_state(
    pause_score: int, normal_score: int, accelerated_score: int
) -> RailRouteScreenState:
    scores = {
        RailRouteScreenState.PAUSED: pause_score,
        RailRouteScreenState.RUNNING: normal_score,
        RailRouteScreenState.OTHER_SPEED: accelerated_score,
    }
    state, score = max(scores.items(), key=lambda item: item[1])
    ordered = sorted(scores.values(), reverse=True)
    if score < _SELECTED_SCORE_MINIMUM:
        return RailRouteScreenState.NOT_GAMEPLAY
    if len(ordered) > 1 and ordered[0] - ordered[1] < 10:
        return RailRouteScreenState.UNKNOWN
    return state
