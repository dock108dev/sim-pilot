"""Strict projections from the Software Inc. v10 read-only product surfaces."""

from __future__ import annotations

from decimal import Decimal

from sim_pilot.game_bridge import GameSnapshot, ObservedEntity
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import (
    ProductCategoryObservation,
    ProductConfiguration,
    ProductFeatureObservation,
    ProductOperatingSystemObservation,
    ProductStage,
    ProductTypeObservation,
    TeamSuitability,
)


def _surface(snapshot: GameSnapshot, name: str):
    matches = [surface for surface in snapshot.surfaces if surface.coverage.surface == name]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(f"{name} surface is unavailable or ambiguous")
    return matches[0]


def _decimal(value: object, label: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SoftwareIncUIValidationError(f"{label} is not observed numeric data")
    return Decimal(str(value))


def _text(value: object, label: str, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise SoftwareIncUIValidationError(f"{label} is not observed text")
    return value.strip()


def _split(value: object, label: str, *, empty: bool = False) -> tuple[str, ...]:
    text = _text(value, label, empty=empty)
    return tuple(sorted({part.strip() for part in text.split("|") if part.strip()}))


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def current_cash(snapshot: GameSnapshot) -> Decimal:
    entities = _surface(snapshot, "finances").entities
    if len(entities) != 1:
        raise SoftwareIncUIValidationError("current company cash is ambiguous")
    return _decimal(entities[0].values.get("cash"), "finances.cash")


def product_type(snapshot: GameSnapshot, name: str) -> ProductTypeObservation:
    matches = [
        entity
        for entity in _surface(snapshot, "product_catalog").entities
        if entity.entity_type == "software_type"
        and str(entity.values.get("name", "")).casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(f"product type {name!r} is unavailable or ambiguous")
    values = matches[0].values
    unlocked = values.get("unlocked")
    in_house = values.get("in_house")
    os_specific = values.get("os_specific")
    if (
        not isinstance(unlocked, bool)
        or not isinstance(in_house, bool)
        or not isinstance(os_specific, bool)
    ):
        raise SoftwareIncUIValidationError("product type availability is not observed")
    return ProductTypeObservation(
        name=_text(values.get("name"), "software_type.name"),
        description=_text(values.get("description"), "software_type.description"),
        categories=_split(values.get("categories"), "software_type.categories"),
        unlocked=unlocked,
        in_house=in_house,
        os_specific=os_specific,
        optimal_development_time=_decimal(
            values.get("optimal_development_time"), "software_type.optimal_development_time"
        ),
    )


def product_category(
    snapshot: GameSnapshot, product_type_name: str, category_name: str
) -> ProductCategoryObservation:
    matches = [
        entity
        for entity in _surface(snapshot, "product_catalog").entities
        if entity.entity_type == "software_category"
        and str(entity.values.get("product_type", "")).casefold() == product_type_name.casefold()
        and str(entity.values.get("name", "")).casefold() == category_name.casefold()
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(
            f"product category {product_type_name!r}/{category_name!r} is unavailable or ambiguous"
        )
    values = matches[0].values
    is_default = values.get("is_default")
    unlocked = values.get("unlocked")
    if not isinstance(is_default, bool) or not isinstance(unlocked, bool):
        raise SoftwareIncUIValidationError("product category availability is not observed")
    return ProductCategoryObservation(
        product_type=_text(values.get("product_type"), "software_category.product_type"),
        name=_text(values.get("name"), "software_category.name"),
        description=_text(values.get("description"), "software_category.description", empty=True),
        ideal_price=_decimal(values.get("ideal_price"), "software_category.ideal_price"),
        is_default=is_default,
        unlocked=unlocked,
    )


def product_features(
    snapshot: GameSnapshot, product_type_name: str
) -> tuple[ProductFeatureObservation, ...]:
    result: list[ProductFeatureObservation] = []
    for entity in _surface(snapshot, "product_catalog").entities:
        if entity.entity_type != "software_feature":
            continue
        values = entity.values
        if str(values.get("product_type", "")).casefold() != product_type_name.casefold():
            continue
        unlocked = values.get("unlocked")
        if not isinstance(unlocked, bool):
            raise SoftwareIncUIValidationError("feature availability is not observed")
        result.append(
            ProductFeatureObservation(
                feature_id=entity.entity_id,
                name=_text(values.get("localized_name"), "software_feature.localized_name"),
                specialization=_text(
                    values.get("specialization"),
                    "software_feature.specialization",
                    empty=True,
                ),
                dependencies=_split(
                    values.get("dependencies"), "software_feature.dependencies", empty=True
                ),
                development_time=_decimal(
                    values.get("development_time"), "software_feature.development_time"
                ),
                code_art_ratio=_decimal(
                    values.get("code_art_ratio"), "software_feature.code_art_ratio"
                ),
                server_requirement=_decimal(
                    values.get("server_requirement"), "software_feature.server_requirement"
                ),
                unlocked=unlocked,
            )
        )
    return tuple(sorted(result, key=lambda item: item.name.casefold()))


def product_ui_state(snapshot: GameSnapshot) -> ObservedEntity:
    matches = [
        entity
        for entity in _surface(snapshot, "product_ui").entities
        if entity.entity_type == "product_ui_state" and entity.entity_id == "current"
    ]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError("product UI state is unavailable or ambiguous")
    return matches[0]


def operating_system_options(
    snapshot: GameSnapshot,
) -> tuple[ProductOperatingSystemObservation, ...]:
    options: list[ProductOperatingSystemObservation] = []
    for entity in _surface(snapshot, "product_ui").entities:
        if entity.entity_type != "operating_system_option":
            continue
        values = entity.values
        selected = values.get("selected")
        userbase = values.get("userbase")
        if (
            not isinstance(selected, bool)
            or not isinstance(userbase, int)
            or isinstance(userbase, bool)
        ):
            raise SoftwareIncUIValidationError(
                "operating-system selection or audience is not observed"
            )
        options.append(
            ProductOperatingSystemObservation(
                product_id=entity.entity_id,
                name=_text(values.get("name"), "operating_system.name"),
                userbase=userbase,
                release_date=_text(values.get("release_date"), "operating_system.release_date"),
                selected=selected,
            )
        )
    return tuple(sorted(options, key=lambda option: (-option.userbase, option.product_id)))


def visible_product_configuration(snapshot: GameSnapshot) -> ProductConfiguration:
    values = product_ui_state(snapshot).values
    if values.get("scene") != "product_configuration":
        raise SoftwareIncUIValidationError("the visible product configuration window is not open")
    selected_type = _text(values.get("selected_type"), "product_ui.selected_type")
    selected = _split(values.get("selected_features"), "product_ui.selected_features")
    feature_by_name = {
        item.name.casefold(): item for item in product_features(snapshot, selected_type)
    }
    missing = [name for name in selected if name.casefold() not in feature_by_name]
    if missing:
        raise SoftwareIncUIValidationError(
            "selected product features are not present in the version-pinned catalog"
        )
    selected_internal_names = {
        feature_by_name[name.casefold()].feature_id.split(":", 1)[-1].casefold()
        for name in selected
    }
    missing_dependencies = sorted(
        {
            dependency
            for name in selected
            for dependency in feature_by_name[name.casefold()].dependencies
            if dependency.casefold() not in selected_internal_names
        },
        key=str.casefold,
    )
    if missing_dependencies:
        raise SoftwareIncUIValidationError(
            "selected product features omit declared dependencies: "
            + ", ".join(missing_dependencies)
        )
    server_requirement = sum(
        (feature_by_name[name.casefold()].server_requirement for name in selected), Decimal("0")
    )
    expected_months = sum(
        (feature_by_name[name.casefold()].development_time for name in selected), Decimal("0")
    )
    if expected_months <= 0:
        type_observation = product_type(snapshot, selected_type)
        expected_months = type_observation.optimal_development_time
    return ProductConfiguration(
        name=_text(values.get("product_name"), "product_ui.product_name"),
        product_type=selected_type,
        category=_text(values.get("selected_category"), "product_ui.selected_category"),
        features=selected,
        operating_systems=_split(
            values.get("selected_operating_systems"), "product_ui.selected_operating_systems"
        ),
        design_teams=_split(values.get("design_teams"), "product_ui.design_teams"),
        development_teams=_split(values.get("development_teams"), "product_ui.development_teams"),
        price=_decimal(values.get("price"), "product_ui.price"),
        server_requirement=server_requirement,
        expected_development_months=expected_months,
        team_issue=_text(values.get("team_issue"), "product_ui.team_issue", empty=True),
    )


def team_suitability(snapshot: GameSnapshot, team_name: str) -> TeamSuitability:
    teams = [
        entity
        for entity in _surface(snapshot, "teams").entities
        if str(entity.values.get("name", "")).casefold() == team_name.casefold()
    ]
    if len(teams) != 1:
        raise SoftwareIncUIValidationError(f"team {team_name!r} is unavailable or ambiguous")
    employees = [
        entity
        for entity in _surface(snapshot, "employees").entities
        if str(entity.values.get("team", "")).casefold() == team_name.casefold()
    ]
    programmer = sum(
        (
            _decimal(item.values.get("skill_programmer"), "employee.skill_programmer")
            for item in employees
        ),
        Decimal("0"),
    )
    designer = sum(
        (
            _decimal(item.values.get("skill_designer"), "employee.skill_designer")
            for item in employees
        ),
        Decimal("0"),
    )
    artist = sum(
        (_decimal(item.values.get("skill_artist"), "employee.skill_artist") for item in employees),
        Decimal("0"),
    )
    active_work = tuple(
        sorted(
            str(item.values.get("name"))
            for item in _surface(snapshot, "work_items").entities
            if team_name in str(item.values.get("assigned_teams", "")).split("|")
            and item.values.get("done") is not True
        )
    )
    education = [
        item
        for item in _surface(snapshot, "education").entities
        if item.entity_type == "employee_specialization"
        and str(item.values.get("employee_id")) in {employee.entity_id for employee in employees}
        and _positive_int(item.values.get("level"))
    ]
    specializations = tuple(sorted({str(item.values.get("specialization")) for item in education}))
    role_specializations = tuple(
        sorted(
            {
                f"{item.values.get('role')}:{item.values.get('specialization')}"
                for item in education
                if str(item.values.get("role", "")).strip()
                and str(item.values.get("specialization", "")).strip()
            }
        )
    )
    reasons: list[str] = []
    if not employees:
        reasons.append("team has no observed employees")
    if programmer <= 0:
        reasons.append("team has no observed Programmer skill")
    if designer <= 0:
        reasons.append("team has no observed Designer skill")
    if active_work:
        reasons.append("team has existing active work")
    return TeamSuitability(
        team_name=team_name,
        employee_count=len(employees),
        programmer_skill=programmer,
        designer_skill=designer,
        artist_skill=artist,
        relevant_specializations=specializations,
        role_specializations=role_specializations,
        active_work=active_work,
        suitable=not reasons,
        reasons=tuple(reasons),
    )


def product_work(snapshot: GameSnapshot, name: str) -> ObservedEntity | None:
    matches = [
        entity
        for entity in _surface(snapshot, "work_items").entities
        if entity.entity_type == "work_item"
        and entity.values.get("is_contract") is False
        and str(entity.values.get("name", "")).casefold() == name.casefold()
    ]
    if len(matches) > 1:
        raise SoftwareIncUIValidationError(f"product work {name!r} is ambiguous")
    return None if not matches else matches[0]


def observed_stage(work: ObservedEntity) -> ProductStage:
    if work.values.get("in_beta") is True:
        return ProductStage.BETA
    work_type = str(work.values.get("work_type", "")).casefold()
    if "design" in work_type:
        return ProductStage.DESIGN
    if "alpha" in work_type or "development" in work_type or "software" in work_type:
        return ProductStage.ALPHA
    raise SoftwareIncUIValidationError("product work stage is not recognized")


__all__ = [
    "current_cash",
    "operating_system_options",
    "observed_stage",
    "product_category",
    "product_features",
    "product_type",
    "product_ui_state",
    "product_work",
    "team_suitability",
    "visible_product_configuration",
]
