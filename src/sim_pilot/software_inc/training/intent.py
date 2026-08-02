"""Strict plain-English parsing for Prompt 6B."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

from sim_pilot.software_inc.errors import SoftwareIncUIValidationError


class TrainingIntentAction(StrEnum):
    RECOMMEND = "recommend"
    START = "start"
    STATUS = "status"
    ADVANCE = "advance"


class TrainingIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    action: TrainingIntentAction
    team_name: str | None = None
    minimum_cash_reserve: Decimal | None = None


_START = re.compile(
    r"^(?:train|educate) one suitable employee from (?P<team>.+?) in system design for "
    r"three months while keeping \$?(?P<reserve>[\d,]+(?:\.\d{1,2})?) "
    r"(?:in )?(?:cash|reserve)$",
    re.IGNORECASE,
)
_RECOMMEND = re.compile(
    r"^recommend (?:one )?suitable employee from (?P<team>.+?) for system design "
    r"education while keeping \$?(?P<reserve>[\d,]+(?:\.\d{1,2})?) "
    r"(?:in )?(?:cash|reserve)$",
    re.IGNORECASE,
)


def parse_training_intent(instruction: str) -> TrainingIntent:
    normalized = " ".join(instruction.strip().split())
    folded = normalized.casefold()
    if folded in {"show education status", "show training status", "training status"}:
        return TrainingIntent(action=TrainingIntentAction.STATUS)
    if folded in {"advance education", "advance training", "continue education"}:
        return TrainingIntent(action=TrainingIntentAction.ADVANCE)
    for pattern, action in (
        (_START, TrainingIntentAction.START),
        (_RECOMMEND, TrainingIntentAction.RECOMMEND),
    ):
        match = pattern.fullmatch(normalized)
        if match is not None:
            try:
                reserve = Decimal(match.group("reserve").replace(",", "")).quantize(Decimal("0.01"))
            except InvalidOperation as error:
                raise SoftwareIncUIValidationError("cash reserve is invalid USD") from error
            return TrainingIntent(
                action=action,
                team_name=" ".join(match.group("team").split()),
                minimum_cash_reserve=reserve,
            )
    raise SoftwareIncUIValidationError(
        "unsupported education request; use `train one suitable employee from Core in System "
        "design for three months while keeping $50,000 in cash`"
    )


__all__ = ["TrainingIntent", "TrainingIntentAction", "parse_training_intent"]
