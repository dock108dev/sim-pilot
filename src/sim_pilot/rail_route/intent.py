"""Deterministic natural-language control intent parsing."""

import re

from sim_pilot.rail_route.errors import RailRouteIntentError
from sim_pilot.rail_route.models import RailRouteAction, RailRouteIntent

_STATUS = re.compile(r"\b(status|state|what(?:'s| is) (?:the )?game doing)\b", re.IGNORECASE)
_PAUSE = re.compile(r"\b(pause|stop|hold)\b", re.IGNORECASE)
_RESUME = re.compile(r"\b(resume|unpause|continue|start)\b", re.IGNORECASE)
_ROUTE = re.compile(r"\b(route|dispatch|signal|platform|train)\b", re.IGNORECASE)
_SET_ROUTE = re.compile(
    r"^(?:please\s+)?set\s+(?:a\s+)?route\s+from\s+"
    r"(?P<origin>[A-Za-z0-9][A-Za-z0-9_-]{0,127})\s+to\s+"
    r"(?P<destination>[A-Za-z0-9][A-Za-z0-9_-]{0,127})(?:\s+please)?$",
    re.IGNORECASE,
)


def parse_control_intent(instruction: str) -> RailRouteIntent:
    normalized = " ".join(instruction.strip().split())
    if not normalized:
        raise RailRouteIntentError("enter a Rail Route instruction")
    route_match = _SET_ROUTE.fullmatch(normalized)
    if route_match:
        return RailRouteIntent(
            instruction=normalized,
            action=RailRouteAction.SET_ROUTE,
            origin_signal=route_match.group("origin"),
            destination_signal=route_match.group("destination"),
        )
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
            "unsupported route instruction; use exactly 'set a route from SIGNAL to SIGNAL'"
        )
    raise RailRouteIntentError(
        "unsupported instruction; verified actions are status, pause, resume, and one set_route"
    )
