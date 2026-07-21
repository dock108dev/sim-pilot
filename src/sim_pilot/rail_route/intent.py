"""Deterministic natural-language control intent parsing."""

import re

from sim_pilot.rail_route.errors import RailRouteIntentError
from sim_pilot.rail_route.models import RailRouteAction, RailRouteIntent

_STATUS = re.compile(r"\b(status|state|what(?:'s| is) (?:the )?game doing)\b", re.IGNORECASE)
_PAUSE = re.compile(r"\b(pause|stop|hold)\b", re.IGNORECASE)
_RESUME = re.compile(r"\b(resume|unpause|continue|start)\b", re.IGNORECASE)
_ROUTE = re.compile(r"\b(route|dispatch|signal|platform|train)\b", re.IGNORECASE)


def parse_control_intent(instruction: str) -> RailRouteIntent:
    normalized = " ".join(instruction.strip().split())
    if not normalized:
        raise RailRouteIntentError("enter a Rail Route instruction")
    matches = [
        (RailRouteAction.STATUS, bool(_STATUS.search(normalized))),
        (RailRouteAction.PAUSE, bool(_PAUSE.search(normalized))),
        (RailRouteAction.RESUME, bool(_RESUME.search(normalized))),
    ]
    selected = [action for action, matched in matches if matched]
    if len(selected) > 1:
        raise RailRouteIntentError("instruction contains conflicting Rail Route actions")
    if selected:
        return RailRouteIntent(instruction=normalized, action=selected[0])
    if _ROUTE.search(normalized):
        raise RailRouteIntentError(
            "route-setting is not enabled: Rail Route exposes no verified semantic route "
            "identity or postcondition through the current adapter"
        )
    raise RailRouteIntentError(
        "unsupported instruction; the verified Rail Route actions are status, pause, and resume"
    )
