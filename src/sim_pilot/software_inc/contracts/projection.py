"""Strict projections from read-only Software Inc. v5 contract surfaces."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from sim_pilot.game_bridge import CoverageStatus, GameSnapshot, ObservationSurface, ObservedEntity
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import ContractObservation, ContractStage, ContractWorkObservation


def available_contracts(snapshot: GameSnapshot) -> tuple[ContractObservation, ...]:
    surface = require_complete_surface(snapshot, "contract_market")
    result = tuple(_contract(snapshot, entity) for entity in surface.entities)
    if len({item.contract_id for item in result}) != len(result):
        raise SoftwareIncUIValidationError("available contract identities are not unique")
    return tuple(sorted(result, key=lambda item: item.display_index))


def active_contract_work(snapshot: GameSnapshot) -> tuple[ContractWorkObservation, ...]:
    surface = require_complete_surface(snapshot, "work_items")
    result: list[ContractWorkObservation] = []
    for entity in surface.entities:
        if entity.entity_type != "work_item" or entity.values.get("is_contract") is not True:
            continue
        contract_id = _text(entity, "contract_identity")
        result.append(
            ContractWorkObservation(
                work_item_id=entity.entity_id,
                contract_id=contract_id,
                contract_name=_text(entity, "contract_name"),
                client=_text(entity, "contract_client", empty=True),
                deadline=_text(entity, "contract_deadline", empty=True),
                deadline_observed=_optional_boolean(entity, "contract_deadline_observed"),
                days_remaining=_decimal(entity, "contract_days_remaining"),
                contract_started=_optional_boolean(entity, "contract_started"),
                reward=_decimal(entity, "contract_reward"),
                penalty=_decimal(entity, "contract_penalty"),
                stage=_stage(entity),
                stage_text=_text(entity, "stage", empty=True),
                progress=_decimal(entity, "progress"),
                minimum_progress=_decimal(entity, "minimum_progress", default=Decimal("0")),
                assigned_teams=_split(_text(entity, "assigned_teams", empty=True)),
                employee_count=_integer(entity, "employee_count"),
                paused=_boolean(entity, "paused"),
                done=_boolean(entity, "done"),
                bugs=_optional_decimal(entity, "bugs"),
                fixed_bugs=_optional_decimal(entity, "fixed_bugs"),
                quality=_optional_decimal(entity, "quality"),
                review_score=_optional_decimal(entity, "review_score"),
                reviews_done=_optional_integer(entity, "reviews_done"),
                in_beta=_optional_boolean(entity, "in_beta"),
                released=_optional_boolean(entity, "released"),
            )
        )
    return tuple(sorted(result, key=lambda item: item.work_item_id))


def find_contract(
    contracts: tuple[ContractObservation, ...], reference: str
) -> ContractObservation:
    wanted = " ".join(reference.casefold().split())
    matches = [
        item
        for item in contracts
        if wanted
        in {
            " ".join(item.contract_id.casefold().split()),
            " ".join(item.name.casefold().split()),
            " ".join(item.client.casefold().split()),
        }
    ]
    if not matches:
        raise SoftwareIncUIValidationError(f"no available contract exactly matches {reference!r}")
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(f"contract reference {reference!r} is ambiguous")
    return matches[0]


def require_complete_surface(snapshot: GameSnapshot, name: str) -> ObservationSurface:
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == name]
    if len(matches) != 1 or matches[0].coverage.status is not CoverageStatus.OBSERVED_COMPLETE:
        detail = (
            matches[0].coverage.detail if len(matches) == 1 else "surface missing or duplicated"
        )
        raise SoftwareIncUIValidationError(f"{name} is not completely observed: {detail}")
    return matches[0]


def _contract(snapshot: GameSnapshot, entity: ObservedEntity) -> ContractObservation:
    if entity.entity_type != "available_contract":
        raise SoftwareIncUIValidationError("contract market contains an unexpected entity type")
    months = _integer(entity, "months")
    days_per_month = _positive_game_state_integer(snapshot, "days_per_month")
    completion_window_days = Decimal(months * days_per_month)
    month_label = "month" if months == 1 else "months"
    day_label = "day" if completion_window_days == 1 else "days"
    return ContractObservation(
        contract_id=entity.entity_id,
        display_index=_integer(entity, "display_index"),
        name=_text(entity, "name"),
        client=_text(entity, "client"),
        software_type=_text(entity, "software_type"),
        software_category=_text(entity, "software_category", empty=True),
        features=_split(_text(entity, "features", empty=True)),
        months=months,
        development_time=_decimal(entity, "dev_time"),
        difficulty=_decimal(entity, "difficulty"),
        art_ratio=_decimal(entity, "art_ratio"),
        minimum_progress=_decimal(entity, "minimum_progress"),
        quality_target=_decimal(entity, "quality_target"),
        reward=_decimal(entity, "reward"),
        penalty=_decimal(entity, "penalty"),
        per_bug_penalty=_decimal(entity, "per_bug_penalty"),
        deadline=(
            f"{months} in-game {month_label} after work starts "
            f"({completion_window_days} in-game {day_label})"
        ),
        days_remaining=completion_window_days,
        game_status=_text(entity, "status", empty=True),
    )


def _positive_game_state_integer(snapshot: GameSnapshot, field: str) -> int:
    value = snapshot.game_state.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SoftwareIncUIValidationError(
            f"{field} is not observed as a positive integer from the current save"
        )
    return value


def _stage(entity: ObservedEntity) -> ContractStage:
    values = entity.values
    if values.get("released") is True:
        return ContractStage.RELEASED
    if values.get("done") is True:
        return ContractStage.COMPLETED
    if values.get("in_beta") is True:
        return ContractStage.BETA
    work_type = _text(entity, "work_type", empty=True).casefold()
    stage = _text(entity, "stage", empty=True).casefold()
    if "design" in work_type or "design" in stage:
        return ContractStage.DESIGN
    if "alpha" in work_type or "alpha" in stage:
        return ContractStage.ALPHA
    if "develop" in stage or "code" in stage or "art" in stage:
        return ContractStage.DEVELOPMENT
    return ContractStage.UNKNOWN


def _text(entity: ObservedEntity, field: str, *, empty: bool = False) -> str:
    value = entity.values.get(field)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not observed text")
    return value


def _decimal(entity: ObservedEntity, field: str, *, default: Decimal | None = None) -> Decimal:
    value = entity.values.get(field)
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is invalid") from error
    if not result.is_finite():
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not finite")
    return result


def _optional_decimal(entity: ObservedEntity, field: str) -> Decimal | None:
    return None if field not in entity.values else _decimal(entity, field)


def _integer(entity: ObservedEntity, field: str) -> int:
    value = entity.values.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not an integer")
    return value


def _optional_integer(entity: ObservedEntity, field: str) -> int | None:
    return None if field not in entity.values else _integer(entity, field)


def _boolean(entity: ObservedEntity, field: str) -> bool:
    value = entity.values.get(field)
    if not isinstance(value, bool):
        raise SoftwareIncUIValidationError(f"{entity.entity_id}.{field} is not boolean")
    return value


def _optional_boolean(entity: ObservedEntity, field: str) -> bool | None:
    return None if field not in entity.values else _boolean(entity, field)


def _split(value: str) -> tuple[str, ...]:
    return tuple(part for part in value.split("|") if part)


__all__ = [
    "active_contract_work",
    "available_contracts",
    "find_contract",
    "require_complete_surface",
]
