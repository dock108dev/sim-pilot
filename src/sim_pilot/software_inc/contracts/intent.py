"""Deterministic plain-English parsing for Prompt 6A terminal commands."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim_pilot.software_inc.errors import SoftwareIncUIValidationError


class ContractIntentAction(StrEnum):
    BROWSE = "browse"
    RECOMMEND = "recommend"
    ACCEPT = "accept"
    ADVANCE = "advance"
    REVIEW = "review"
    PROMOTE = "promote"
    RELEASE = "release"


class ContractIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    action: ContractIntentAction
    team_name: str | None = Field(default=None, min_length=1, max_length=64)
    minimum_reward: Decimal | None = Field(default=None, ge=0)
    minimum_cash_reserve: Decimal = Field(default=Decimal("0"), ge=0)

    @model_validator(mode="after")
    def validate_shape(self) -> ContractIntent:
        needs_constraints = self.action in {
            ContractIntentAction.RECOMMEND,
            ContractIntentAction.ACCEPT,
        }
        if needs_constraints != (self.team_name is not None and self.minimum_reward is not None):
            raise ValueError("recommendation and acceptance require exact team and reward floor")
        return self


_RECOMMEND = re.compile(
    r"^(?:find|recommend|show)(?: me)? (?:one |a )?(?:small |suitable )?contract "
    r"(?:for|that) (?P<team>.+?)(?: can complete)? (?:with|for|if the) reward "
    r"(?:is )?(?:at least|of at least) \$?(?P<reward>[\d,]+(?:\.\d{1,2})?)"
    r"(?: (?:while keeping|and keep) \$?(?P<reserve>[\d,]+(?:\.\d{1,2})?) "
    r"(?:in )?(?:cash|reserve))?$",
    re.IGNORECASE,
)
_ACCEPT = re.compile(
    r"^accept (?:one |the )?(?:recommended |suitable )?contract "
    r"(?:for|with) (?P<team>.+?) (?:with|for|if the) reward (?:is )?"
    r"(?:at least|of at least) \$?(?P<reward>[\d,]+(?:\.\d{1,2})?)"
    r"(?: (?:while keeping|and keep) \$?(?P<reserve>[\d,]+(?:\.\d{1,2})?) "
    r"(?:in )?(?:cash|reserve))?$",
    re.IGNORECASE,
)


def parse_contract_intent(instruction: str) -> ContractIntent:
    normalized = " ".join(instruction.strip().split())
    folded = normalized.casefold()
    if folded in {"browse contracts", "open contracts", "show available contracts"}:
        return ContractIntent(action=ContractIntentAction.BROWSE)
    if folded in {"advance the current contract", "work on the current contract"}:
        return ContractIntent(action=ContractIntentAction.ADVANCE)
    if folded in {"review the current contract", "review the contract"}:
        return ContractIntent(action=ContractIntentAction.REVIEW)
    if folded in {"promote the current contract", "promote the contract"}:
        return ContractIntent(action=ContractIntentAction.PROMOTE)
    if folded in {"release the current contract", "release the contract"}:
        return ContractIntent(action=ContractIntentAction.RELEASE)
    for pattern, action in (
        (_RECOMMEND, ContractIntentAction.RECOMMEND),
        (_ACCEPT, ContractIntentAction.ACCEPT),
    ):
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        return ContractIntent(
            action=action,
            team_name=" ".join(match.group("team").split()),
            minimum_reward=_money(match.group("reward")),
            minimum_cash_reserve=_money(match.group("reserve") or "0"),
        )
    raise SoftwareIncUIValidationError(
        "unsupported contract request; name an exact team and reward floor, for example "
        "`find a small contract for Core with reward at least $10,000`"
    )


def _money(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", "")).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise SoftwareIncUIValidationError("contract money constraint is invalid USD") from error


__all__ = ["ContractIntent", "ContractIntentAction", "parse_contract_intent"]
