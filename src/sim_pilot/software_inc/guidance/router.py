"""Deterministic interaction routing for the Software Inc. terminal session."""

from __future__ import annotations

import re

from sim_pilot.guidance import InteractionClassification, InteractionKind

_QUESTION_PREFIXES = (
    "am i ",
    "can sim pilot ",
    "can you ",
    "do i ",
    "how ",
    "is ",
    "what ",
    "when ",
    "which ",
    "who ",
    "why ",
)
_RECOMMENDATION_FORMS = {
    "recommend",
    "recommend something",
    "what do you recommend",
    "what should i do",
    "what should i do next",
}
_EXPLANATION_PREFIXES = (
    "why did you recommend",
    "why are you recommending",
    "explain your recommendation",
)
_ACTION_PREFIXES = (
    "open manage teams",
    "pause",
    "pause the game",
    "resume",
    "resume the game",
    "create a team",
    "hire one programmer",
    "observe programmer applicants",
    "prepare one workstation",
    "place a workstation",
    "set up one workstation",
    "setup one workstation",
    "begin a small game engine called atlas",
    "i want to make a small game engine called atlas",
    "create a game engine called atlas",
    "advance atlas",
    "review atlas",
    "iterate atlas",
    "promote atlas",
    "hold atlas",
    "resume atlas",
)
_OFFICE_ACTIONS = (
    re.compile(r"^(?:set|configure) .+? (?:team )?working hours (?:to|from) .+$"),
    re.compile(
        r"^(?:assign|set) .+? (?:as|to) "
        r"(?:lead|programmer|designer|artist|service) (?:for|on) .+$"
    ),
)


def classify_interaction(value: str) -> InteractionClassification:
    stripped = value.strip()
    normalized = " ".join(stripped.casefold().replace("-", " ").split())
    if not normalized:
        return InteractionClassification(
            kind=InteractionKind.UNKNOWN,
            normalized_input="empty",
            deterministic=True,
            clarification_required=True,
            source="deterministic",
        )
    if normalized.startswith("/"):
        return _classify_slash(stripped, normalized)
    if normalized in _RECOMMENDATION_FORMS or normalized.startswith("should i "):
        return _classification(InteractionKind.RECOMMENDATION, normalized)
    if normalized.startswith(_EXPLANATION_PREFIXES):
        return _classification(InteractionKind.EXPLANATION, normalized)
    if normalized in {"status", "show status", "company status"}:
        return _classification(InteractionKind.STATUS, normalized)
    if normalized in {"capabilities", "show capabilities"}:
        return _classification(InteractionKind.CAPABILITIES, normalized)
    if normalized.startswith(_QUESTION_PREFIXES) or stripped.endswith("?"):
        return _classification(InteractionKind.QUESTION, normalized)
    if normalized.startswith(_ACTION_PREFIXES) or any(
        pattern.fullmatch(normalized) for pattern in _OFFICE_ACTIONS
    ):
        return InteractionClassification(
            kind=InteractionKind.DELEGATION,
            normalized_input=normalized,
            deterministic=True,
            mutation_permitted=True,
            objective=stripped,
            source="deterministic",
        )
    return InteractionClassification(
        kind=InteractionKind.UNKNOWN,
        normalized_input=normalized,
        deterministic=True,
        clarification_required=True,
        source="deterministic",
    )


def _classify_slash(original: str, normalized: str) -> InteractionClassification:
    match = re.fullmatch(r"/(?P<command>[a-z_]+)(?:\s+(?P<argument>.*))?", normalized)
    if match is None:
        return InteractionClassification(
            kind=InteractionKind.UNKNOWN,
            normalized_input=normalized,
            deterministic=True,
            clarification_required=True,
            source="slash_command",
        )
    command = match.group("command")
    argument = match.group("argument")
    mapping = {
        "capabilities": InteractionKind.CAPABILITIES,
        "crash_course": InteractionKind.CRASH_COURSE,
        "help": InteractionKind.HELP,
        "quit": InteractionKind.QUIT,
        "recommend": InteractionKind.RECOMMENDATION,
        "status": InteractionKind.STATUS,
        "why": InteractionKind.EXPLANATION,
    }
    if command == "operate":
        if not argument:
            return InteractionClassification(
                kind=InteractionKind.DELEGATION,
                normalized_input=normalized,
                deterministic=True,
                clarification_required=True,
                objective="missing objective",
                source="slash_command",
            )
        objective = original.strip()[len("/operate") :].strip()
        return InteractionClassification(
            kind=InteractionKind.DELEGATION,
            normalized_input=normalized,
            deterministic=True,
            mutation_permitted=True,
            objective=objective,
            source="slash_command",
        )
    kind = mapping.get(command)
    if kind is None:
        return InteractionClassification(
            kind=InteractionKind.UNKNOWN,
            normalized_input=normalized,
            deterministic=True,
            clarification_required=True,
            source="slash_command",
        )
    topic = (
        argument.replace(" ", "_") if kind is InteractionKind.CRASH_COURSE and argument else None
    )
    return InteractionClassification(
        kind=kind,
        normalized_input=normalized,
        deterministic=True,
        topic=topic,
        source="slash_command",
    )


def _classification(kind: InteractionKind, normalized: str) -> InteractionClassification:
    return InteractionClassification(
        kind=kind,
        normalized_input=normalized,
        deterministic=True,
        source="deterministic",
    )


__all__ = ["classify_interaction"]
