"""Deterministic plain-English parsing for the bounded Prompt 7 Atlas slice."""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .contract import (
    ATLAS_DEFAULT_RESERVE,
    ATLAS_NAME,
    ATLAS_PRODUCT_TYPE,
    ATLAS_TEAM,
)


class ProductIntentAction(StrEnum):
    CREATE = "create"
    STATUS = "status"
    ADVANCE = "advance"
    REVIEW = "review"
    ITERATE = "iterate"
    PROMOTE = "promote"
    HOLD = "hold"
    RESUME = "resume"


class ProductIntent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    schema_version: int = 1
    action: ProductIntentAction
    product_name: str = ATLAS_NAME
    product_type: str = ATLAS_PRODUCT_TYPE
    requested_product_type: str = ATLAS_PRODUCT_TYPE
    mapping_note: str = ""
    team_name: str = ATLAS_TEAM
    minimum_cash_reserve: Decimal = Field(default=ATLAS_DEFAULT_RESERVE, ge=0)


def parse_product_intent(text: str) -> ProductIntent:
    folded = " ".join(text.strip().casefold().split())
    if not folded:
        raise SoftwareIncUIValidationError("product intent cannot be empty")
    reserve_match = re.search(r"(?:keep|reserve|maintain)[^$]*\$?([0-9][0-9,]*)", folded)
    reserve = (
        Decimal(reserve_match.group(1).replace(",", ""))
        if reserve_match is not None
        else ATLAS_DEFAULT_RESERVE
    )
    if "atlas" in folded and any(
        word in folded for word in ("begin", "create", "make", "start", "develop")
    ):
        requested_type = (
            "Game Engine"
            if "game engine" in folded
            else ATLAS_PRODUCT_TYPE
            if any(value in folded for value in ("2d editor", "2-d editor"))
            else ""
        )
        if not requested_type:
            raise SoftwareIncUIValidationError(
                f"Prompt 7 creation requires the explicit product type {ATLAS_PRODUCT_TYPE}"
            )
        mapping_note = (
            "Software Inc. 1.8.41 has no Game Engine product type; the user-approved current "
            "equivalent is the in-house 2D Editor type."
            if requested_type == "Game Engine"
            else ""
        )
        return ProductIntent(
            action=ProductIntentAction.CREATE,
            requested_product_type=requested_type,
            mapping_note=mapping_note,
            minimum_cash_reserve=reserve,
        )
    exact = {
        "status atlas": ProductIntentAction.STATUS,
        "show atlas": ProductIntentAction.STATUS,
        "advance atlas": ProductIntentAction.ADVANCE,
        "review atlas": ProductIntentAction.REVIEW,
        "iterate atlas": ProductIntentAction.ITERATE,
        "promote atlas": ProductIntentAction.PROMOTE,
        "hold atlas": ProductIntentAction.HOLD,
        "pause atlas": ProductIntentAction.HOLD,
        "resume atlas": ProductIntentAction.RESUME,
    }
    if folded in exact:
        return ProductIntent(action=exact[folded])
    raise SoftwareIncUIValidationError(
        "unsupported product intent; use create, status, advance, review, iterate, promote, "
        "hold, or resume Atlas"
    )


__all__ = ["ProductIntent", "ProductIntentAction", "parse_product_intent"]
