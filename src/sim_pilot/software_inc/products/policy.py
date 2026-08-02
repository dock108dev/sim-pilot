"""Deterministic Atlas recommendation and conservative runway policy."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .contract import (
    ATLAS_CATEGORY,
    ATLAS_DEFAULT_RESERVE,
    ATLAS_FEATURES,
    ATLAS_NAME,
    ATLAS_PRODUCT_TYPE,
    ATLAS_TEAM,
)
from .models import ProductRecommendation, ProductRunway
from .projection import (
    current_cash,
    operating_system_options,
    product_category,
    product_features,
    product_type,
    team_suitability,
    visible_product_configuration,
)

_TTL = timedelta(minutes=3)


def _numeric_sum(snapshot: GameSnapshot, surface_name: str, field: str) -> Decimal:
    surfaces = [
        surface for surface in snapshot.surfaces if surface.coverage.surface == surface_name
    ]
    if len(surfaces) != 1:
        raise SoftwareIncUIValidationError(f"{surface_name} is unavailable or ambiguous")
    total = Decimal("0")
    for entity in surfaces[0].entities:
        value = entity.values.get(field)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SoftwareIncUIValidationError(f"{surface_name}.{field} is not numeric")
        total += Decimal(str(value))
    return total


def recommend_atlas(
    snapshot: GameSnapshot,
    *,
    name: str = ATLAS_NAME,
    team_name: str = ATLAS_TEAM,
    minimum_cash_reserve: Decimal = ATLAS_DEFAULT_RESERVE,
    now: datetime | None = None,
) -> ProductRecommendation:
    if " ".join(name.split()).casefold() != ATLAS_NAME.casefold():
        raise SoftwareIncUIValidationError("Prompt 7 supports only the exact product name Atlas")
    if minimum_cash_reserve < 0:
        raise SoftwareIncUIValidationError("minimum cash reserve cannot be negative")
    type_observation = product_type(snapshot, ATLAS_PRODUCT_TYPE)
    category_observation = product_category(snapshot, ATLAS_PRODUCT_TYPE, ATLAS_CATEGORY)
    configuration = visible_product_configuration(snapshot)
    team = team_suitability(snapshot, team_name)
    cash = current_cash(snapshot)
    payroll = _numeric_sum(snapshot, "employees", "salary")
    infrastructure = _numeric_sum(snapshot, "infrastructure", "recurring_cost")
    months = max(
        Decimal("1"),
        configuration.expected_development_months.to_integral_value(rounding=ROUND_CEILING),
    )
    recurring = (payroll + infrastructure) * months
    known_one_time = Decimal("0")
    cash_after = cash - recurring - known_one_time
    runway = ProductRunway(
        observed_cash=cash,
        minimum_cash_reserve=minimum_cash_reserve,
        observed_monthly_payroll=payroll,
        observed_monthly_infrastructure=infrastructure,
        conservative_months=months,
        conservative_recurring_cost=recurring,
        known_one_time_cost=known_one_time,
        projected_cash_after=cash_after,
    )
    reasons: list[str] = []
    if not type_observation.unlocked:
        reasons.append(f"{ATLAS_PRODUCT_TYPE} is not unlocked in the observed year")
    if not type_observation.in_house:
        reasons.append(f"{ATLAS_PRODUCT_TYPE} is not observed as an in-house development tool")
    if not category_observation.unlocked:
        reasons.append(f"{ATLAS_PRODUCT_TYPE}/{ATLAS_CATEGORY} is not unlocked")
    if configuration.name.casefold() != ATLAS_NAME.casefold():
        reasons.append("visible product name is not exactly Atlas")
    if configuration.product_type.casefold() != ATLAS_PRODUCT_TYPE.casefold():
        reasons.append(f"visible product type is not {ATLAS_PRODUCT_TYPE}")
    if configuration.category.casefold() != ATLAS_CATEGORY.casefold():
        reasons.append(f"visible product category is not {ATLAS_CATEGORY}")
    if configuration.features != ATLAS_FEATURES:
        reasons.append(
            "visible feature set is not the exact bounded set " + ", ".join(ATLAS_FEATURES)
        )
    if configuration.price != category_observation.ideal_price:
        reasons.append(
            f"visible price ${configuration.price:,.2f} is not the observed ideal price "
            f"${category_observation.ideal_price:,.2f}"
        )
    if {value.casefold() for value in configuration.design_teams} != {team_name.casefold()}:
        reasons.append("design team selection is not exactly Core")
    if {value.casefold() for value in configuration.development_teams} != {team_name.casefold()}:
        reasons.append("development team selection is not exactly Core")
    if configuration.team_issue.strip():
        reasons.append("the game reports a team issue: " + configuration.team_issue.strip())
    if not team.suitable:
        reasons.extend(team.reasons)
    selected_features = {
        feature.name.casefold(): feature
        for feature in product_features(snapshot, configuration.product_type)
        if feature.name.casefold() in {name.casefold() for name in configuration.features}
    }
    required_specializations = {
        feature.specialization
        for feature in selected_features.values()
        if feature.specialization.strip()
    }
    missing_specializations = sorted(
        required_specializations - set(team.relevant_specializations), key=str.casefold
    )
    if missing_specializations:
        reasons.append(
            "Core has no observed positive specialization level for selected feature domain(s): "
            + ", ".join(missing_specializations)
        )
    required_role_specializations = {
        f"Designer:{specialization}" for specialization in required_specializations
    } | {f"Programmer:{specialization}" for specialization in required_specializations}
    missing_role_specializations = sorted(
        required_role_specializations - set(team.role_specializations), key=str.casefold
    )
    if missing_role_specializations:
        reasons.append(
            "Core lacks observed positive role specialization(s): "
            + ", ".join(missing_role_specializations)
        )
    options = operating_system_options(snapshot)
    expected_operating_systems = (
        (f"{options[0].product_id}:{options[0].name}",)
        if type_observation.os_specific and options
        else ()
    )
    if configuration.operating_systems != expected_operating_systems:
        reasons.append(
            "visible operating-system set is not the one exact highest-userbase observed option"
        )
    catalog = next(
        surface for surface in snapshot.surfaces if surface.coverage.surface == "product_catalog"
    )
    required_product_types = {
        str(entity.values.get("required_product_type", ""))
        for entity in catalog.entities
        if entity.entity_type == "product_prerequisite"
        and str(entity.values.get("product_type", "")).casefold()
        == configuration.product_type.casefold()
        and str(entity.values.get("category", "")).casefold() == configuration.category.casefold()
    }
    released_types = {
        str(entity.values.get("type", ""))
        for surface in snapshot.surfaces
        if surface.coverage.surface == "products"
        for entity in surface.entities
        if entity.entity_type == "product"
    }
    unresolved_product_prerequisites = sorted(
        required_product_types - released_types, key=str.casefold
    )
    if unresolved_product_prerequisites:
        reasons.append(
            "selected category has unresolved product prerequisite(s): "
            + ", ".join(unresolved_product_prerequisites)
        )
    if configuration.server_requirement > 0:
        reasons.append(
            "selected features have a non-zero server requirement that Prompt 7 cannot yet "
            "bind to a verified product server"
        )
    if cash_after < minimum_cash_reserve:
        reasons.append(
            f"conservative runway projects ${cash_after:,.2f}, below the "
            f"${minimum_cash_reserve:,.2f} reserve"
        )
    current = now or datetime.now(UTC)
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    material = {
        "adapter": snapshot.adapter_version,
        "session": snapshot.game_session_id,
        "save": save_identity,
        "sequence": snapshot.bridge_sequence,
        "configuration": configuration.model_dump(mode="json"),
        "team": team.model_dump(mode="json"),
        "runway": runway.model_dump(mode="json"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return ProductRecommendation(
        recommendation_id=f"product-recommendation:{fingerprint[:24]}",
        game_session_id=snapshot.game_session_id,
        save_identity=save_identity,
        source_bridge_sequence=snapshot.bridge_sequence,
        capability_fingerprint=fingerprint,
        configuration=configuration,
        runway=runway,
        team=team,
        recommended=not reasons,
        reasons=tuple(reasons),
        material_unknowns=(
            "The estimate treats observed payroll and server-group cost as continuing for every "
            "conservative development month.",
            "Forecast sales and other future revenue are excluded.",
            "Licensing and operating-system costs are not counted unless the current design UI "
            "exposes them as an exact charge; creation must stop if the game presents one.",
            "The selected feature development-time value is treated as game-owned development "
            "months; the public SoftwareType API names its related specialization projection "
            "GetSpecializationMonths.",
            "Software Inc. 1.8.41 transitions from Design to Alpha; Alpha is its development "
            "phase, so no separate invented Development stage is claimed.",
        ),
        created_at=current,
        expires_at=current + _TTL,
    )


__all__ = ["recommend_atlas"]
