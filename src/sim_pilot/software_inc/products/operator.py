"""Verified visible-UI operator for the bounded Atlas lifecycle."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from sim_pilot.computer_control.models import (
    DesktopFrame,
    InputGesture,
    InputGestureKind,
    KeyModifier,
)
from sim_pilot.game_bridge import GameSnapshot, ObservedEntity
from sim_pilot.software_inc.errors import (
    SoftwareIncUIObservationError,
    SoftwareIncUIValidationError,
    SoftwareIncUIVerificationError,
)
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    VisualTarget,
)
from sim_pilot.software_inc.ui.observer import ObservedSoftwareIncUI, SoftwareIncUIObserver

from .contract import (
    ATLAS_CATEGORY,
    ATLAS_DEFAULT_RESERVE,
    ATLAS_FEATURES,
    ATLAS_NAME,
    ATLAS_PRODUCT_TYPE,
    ATLAS_TEAM,
)
from .models import (
    ProductApproval,
    ProductCommitment,
    ProductCycleEvent,
    ProductOperationResult,
    ProductRecommendation,
    ProductStage,
    ProductWorkflow,
    ProductWorkflowStatus,
)
from .policy import recommend_atlas
from .projection import (
    current_cash,
    observed_stage,
    operating_system_options,
    product_category,
    product_features,
    product_ui_state,
    product_work,
)
from .store import ProductWorkflowStore
from .workflow import approval_for, create_workflow, resolve_approval, synchronize_workflow

ApprovalProvider = Callable[[ProductApproval], bool]
ProgressProvider = Callable[[str], None]
ObserverFactory = Callable[[], "ProductObserver"]
_SETTLE_SECONDS = 0.25
_MAXIMUM_SETUP_CYCLES = 36


class ProductInputBackend(Protocol):
    def execute(self, gesture: InputGesture, *, frame: DesktopFrame) -> object: ...


class ProductObserver(Protocol):
    @property
    def backend(self) -> ProductInputBackend: ...

    async def observe(self) -> ObservedSoftwareIncUI: ...

    async def keep_game_foreground(self) -> None: ...


async def close_product_configuration(
    *,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
) -> ProductOperationResult:
    """Close only the reversible product configuration window with verification."""
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    if before.observation.scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
        return _result(
            None, 0, True, False, "Product configuration is already closed; no input was sent."
        )
    if before.observation.scene is not SoftwareIncUIScene.PRODUCT_CONFIGURATION:
        raise SoftwareIncUIValidationError(
            f"cannot close product configuration from {before.observation.scene.value}"
        )
    target = _target(before.observation, "close_product_configuration")
    if dry_run:
        return _result(
            None,
            0,
            False,
            True,
            "Dry run: would close the reversible product configuration window; no input sent.",
        )
    after = await _click(
        observer,
        before,
        target,
        "close the reversible product configuration window",
    )
    if after.observation.scene is not SoftwareIncUIScene.GAMEPLAY_PAUSED:
        raise SoftwareIncUIVerificationError(
            "product configuration did not close to paused gameplay; no retry attempted"
        )
    return _result(None, 1, True, False, "Product configuration closed and pause verified.")


async def start_atlas(
    *,
    minimum_cash_reserve: Decimal = ATLAS_DEFAULT_RESERVE,
    approval_provider: ApprovalProvider | None = None,
    dry_run: bool = False,
    progress_provider: ProgressProvider | None = None,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ProductWorkflowStore | None = None,
) -> ProductOperationResult:
    repository = store or ProductWorkflowStore()
    observer = observer_factory()
    if progress_provider is not None:
        progress_provider("observing the current paused save")
    current = await observer.observe()
    _require_actionable(current.observation)
    if not current.observation.paused:
        raise SoftwareIncUIValidationError(
            "pause the game before configuring Atlas; no product input was sent"
        )
    snapshot = current.observation.semantic_after
    existing_work = product_work(snapshot, ATLAS_NAME)
    if existing_work is not None:
        workflow = _existing_or_recovered_workflow(repository, snapshot, existing_work)
        return _result(
            workflow,
            0,
            True,
            False,
            "Atlas already exists in this save; duplicate creation was rejected with no input.",
        )
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    existing = repository.current(
        game_session_id=snapshot.game_session_id, save_identity=save_identity
    )
    if existing is not None:
        pending = existing.pending_approval
        safely_uncommitted = (
            pending is not None
            and pending.commitment is ProductCommitment.CREATE
            and pending.approved in {None, False}
        )
        if not safely_uncommitted:
            raise SoftwareIncUIValidationError(
                "an approved or active Atlas workflow exists but its exact product work is not "
                "observed; commitment outcome is ambiguous and will not be retried"
            )
        if dry_run:
            return _result(
                existing,
                0,
                False,
                True,
                "A prior uncommitted Atlas approval is pending or denied; a live start would "
                "expire it and rebind a fresh configuration. No input or persistence changed.",
            )
        repository.save(
            existing.model_copy(
                update={
                    "status": ProductWorkflowStatus.FAILED,
                    "updated_at": datetime.now(UTC),
                }
            )
        )
    gestures = 0
    recommendation: ProductRecommendation | None = None
    selecting_team: str | None = None
    name_text_selected = False
    price_text_selected = False
    for _cycle in range(1, _MAXIMUM_SETUP_CYCLES + 1):
        observation = current.observation
        scene = observation.scene
        if progress_provider is not None:
            progress_provider(f"setup cycle {_cycle}: verified scene {scene.value}")
        if scene is SoftwareIncUIScene.GAMEPLAY_PAUSED:
            if dry_run:
                return _result(
                    None,
                    gestures,
                    False,
                    True,
                    "Dry run: would open the current-frame New software design window; "
                    "no input sent.",
                )
            current = await _click(
                observer,
                current,
                _target(observation, "open_product_design"),
                "open the visible New software design window",
            )
            gestures += 1
            if current.observation.scene is not SoftwareIncUIScene.PRODUCT_CONFIGURATION:
                raise SoftwareIncUIVerificationError(
                    "open product-design input did not produce the exact configuration scene; "
                    "no retry attempted"
                )
            continue
        if scene is SoftwareIncUIScene.PRODUCT_TEAM_SELECTION:
            selected = set(
                _product_ui_text(observation, "team_picker_selected", empty=True).split("|")
            )
            selected.discard("")
            if selected != {ATLAS_TEAM}:
                target_name = next(iter(sorted(selected - {ATLAS_TEAM})), ATLAS_TEAM)
                if dry_run:
                    return _result(
                        None,
                        gestures,
                        False,
                        True,
                        f"Dry run: would select exact team set Core by toggling {target_name!r}.",
                    )
                current = await _click(
                    observer,
                    current,
                    _target(observation, f"product_team_{target_name}"),
                    f"set exact product team selection to Core by toggling {target_name!r}",
                )
                gestures += 1
                expected = selected ^ {target_name}
                observed = set(
                    _product_ui_text(current.observation, "team_picker_selected", empty=True).split(
                        "|"
                    )
                )
                observed.discard("")
                if observed != expected:
                    raise SoftwareIncUIVerificationError(
                        "team-selection toggle did not produce the exact expected set; "
                        "no retry attempted"
                    )
                continue
            if dry_run:
                return _result(
                    None,
                    gestures,
                    False,
                    True,
                    "Dry run: would apply exact Core team selection.",
                )
            current = await _click(
                observer,
                current,
                _target(observation, "apply_product_teams"),
                "apply exact Core product team selection",
            )
            gestures += 1
            if current.observation.scene is not SoftwareIncUIScene.PRODUCT_CONFIGURATION:
                raise SoftwareIncUIVerificationError(
                    "applying product teams did not return to product configuration; "
                    "no retry attempted"
                )
            assert selecting_team is not None
            applied = set(
                _product_ui_text(current.observation, f"{selecting_team}_teams", empty=True).split(
                    "|"
                )
            )
            applied.discard("")
            if applied != {ATLAS_TEAM}:
                raise SoftwareIncUIVerificationError(
                    f"applying {selecting_team} team did not produce exact Core assignment; "
                    "no retry attempted"
                )
            selecting_team = None
            continue
        if scene is not SoftwareIncUIScene.PRODUCT_CONFIGURATION:
            raise SoftwareIncUIValidationError(
                f"Atlas configuration cannot continue from {scene.value}; close unrelated UI"
            )
        state = product_ui_state(observation.semantic_after).values
        selected_type = _product_ui_text(observation, "selected_type", empty=True)
        if selected_type.casefold() != ATLAS_PRODUCT_TYPE.casefold():
            target_id = (
                "product_combo_item:2d editor"
                if _has_target(observation, "product_combo_item:2d editor")
                else "product_type_combo"
            )
            if dry_run:
                return _result(None, gestures, False, True, f"Dry run: would click {target_id}.")
            current = await _click(
                observer,
                current,
                _target(observation, target_id),
                f"select exact {ATLAS_PRODUCT_TYPE} type",
            )
            gestures += 1
            if target_id == "product_type_combo":
                if not _has_target(current.observation, "product_combo_item:2d editor"):
                    raise SoftwareIncUIVerificationError(
                        "product-type menu did not expose exact 2D Editor; no retry attempted"
                    )
            elif (
                _product_ui_text(current.observation, "selected_type", empty=True).casefold()
                != ATLAS_PRODUCT_TYPE.casefold()
            ):
                raise SoftwareIncUIVerificationError(
                    "product-type selection did not become exact 2D Editor; no retry attempted"
                )
            continue
        selected_category = _product_ui_text(observation, "selected_category", empty=True)
        if selected_category.casefold() != ATLAS_CATEGORY.casefold():
            target_id = (
                "product_combo_item:default"
                if _has_target(observation, "product_combo_item:default")
                else "product_category_combo"
            )
            if dry_run:
                return _result(None, gestures, False, True, f"Dry run: would click {target_id}.")
            current = await _click(
                observer,
                current,
                _target(observation, target_id),
                f"select exact {ATLAS_CATEGORY} product category",
            )
            gestures += 1
            if target_id == "product_category_combo":
                if not _has_target(current.observation, "product_combo_item:default"):
                    raise SoftwareIncUIVerificationError(
                        "product-category menu did not expose exact Default; no retry attempted"
                    )
            elif (
                _product_ui_text(current.observation, "selected_category", empty=True).casefold()
                != ATLAS_CATEGORY.casefold()
            ):
                raise SoftwareIncUIVerificationError(
                    "product-category selection did not become exact Default; no retry attempted"
                )
            continue
        product_name = _product_ui_text(observation, "product_name", empty=True)
        if product_name != ATLAS_NAME:
            if state.get("product_name_focused") is not True:
                if dry_run:
                    return _result(
                        None, gestures, False, True, "Dry run: would focus product name."
                    )
                current = await _click(
                    observer,
                    current,
                    _target(observation, "product_name_input"),
                    "focus the exact product-name field",
                )
                if (
                    product_ui_state(current.observation.semantic_after).values.get(
                        "product_name_focused"
                    )
                    is not True
                ):
                    raise SoftwareIncUIVerificationError(
                        "product-name field did not receive focus; no retry attempted"
                    )
            elif product_name and not name_text_selected:
                if dry_run:
                    return _result(
                        None, gestures, False, True, "Dry run: would select existing name text."
                    )
                current = await _key(
                    observer,
                    current,
                    key_code=0,
                    modifiers=(KeyModifier.COMMAND,),
                    target_id="product_name_input",
                    effect="select existing product-name text",
                )
                name_text_selected = True
                if (
                    product_ui_state(current.observation.semantic_after).values.get(
                        "product_name_focused"
                    )
                    is not True
                ):
                    raise SoftwareIncUIVerificationError(
                        "product-name selection lost exact field focus; no retry attempted"
                    )
            elif name_text_selected:
                if dry_run:
                    return _result(
                        None, gestures, False, True, "Dry run: would clear selected name text."
                    )
                current = await _key(
                    observer,
                    current,
                    key_code=51,
                    modifiers=(),
                    target_id="product_name_input",
                    effect="clear selected product-name text",
                )
                name_text_selected = False
                if _product_ui_text(current.observation, "product_name", empty=True):
                    raise SoftwareIncUIVerificationError(
                        "selected product-name text did not clear; no retry attempted"
                    )
            else:
                if dry_run:
                    return _result(None, gestures, False, True, "Dry run: would type Atlas.")
                current = await _text(
                    observer,
                    current,
                    ATLAS_NAME,
                    "product_name_input",
                    "type exact product name Atlas",
                )
                name_text_selected = False
                if _product_ui_text(current.observation, "product_name", empty=True) != ATLAS_NAME:
                    raise SoftwareIncUIVerificationError(
                        "product name did not become exact Atlas; no retry attempted"
                    )
            gestures += 1
            continue
        name_text_selected = False
        ideal_price = product_category(
            observation.semantic_after, ATLAS_PRODUCT_TYPE, ATLAS_CATEGORY
        ).ideal_price
        observed_price = state.get("price")
        if isinstance(observed_price, bool) or not isinstance(observed_price, (int, float)):
            raise SoftwareIncUIValidationError("product_ui.price is not observed numeric data")
        if Decimal(str(observed_price)) != ideal_price:
            price_text = _product_ui_text(observation, "price_text", empty=True)
            if state.get("price_focused") is not True:
                if dry_run:
                    return _result(
                        None, gestures, False, True, "Dry run: would focus product price."
                    )
                current = await _click(
                    observer,
                    current,
                    _target(observation, "product_price_input"),
                    "focus the exact product-price field",
                )
                if (
                    product_ui_state(current.observation.semantic_after).values.get("price_focused")
                    is not True
                ):
                    raise SoftwareIncUIVerificationError(
                        "product-price field did not receive focus; no retry attempted"
                    )
            elif price_text and not price_text_selected:
                if dry_run:
                    return _result(
                        None, gestures, False, True, "Dry run: would select existing price text."
                    )
                current = await _key(
                    observer,
                    current,
                    key_code=0,
                    modifiers=(KeyModifier.COMMAND,),
                    target_id="product_price_input",
                    effect="select existing product-price text",
                )
                price_text_selected = True
                if (
                    product_ui_state(current.observation.semantic_after).values.get("price_focused")
                    is not True
                ):
                    raise SoftwareIncUIVerificationError(
                        "product-price selection lost exact field focus; no retry attempted"
                    )
            elif price_text_selected:
                if dry_run:
                    return _result(
                        None, gestures, False, True, "Dry run: would clear selected price text."
                    )
                current = await _key(
                    observer,
                    current,
                    key_code=51,
                    modifiers=(),
                    target_id="product_price_input",
                    effect="clear selected product-price text",
                )
                price_text_selected = False
                if _product_ui_text(current.observation, "price_text", empty=True):
                    raise SoftwareIncUIVerificationError(
                        "selected product-price text did not clear; no retry attempted"
                    )
            else:
                if dry_run:
                    return _result(
                        None,
                        gestures,
                        False,
                        True,
                        f"Dry run: would set the observed ideal price ${ideal_price:,.2f}.",
                    )
                current = await _text(
                    observer,
                    current,
                    format(ideal_price, "f"),
                    "product_price_input",
                    f"set exact observed ideal price ${ideal_price:,.2f}",
                )
                price_text_selected = False
                updated_price = product_ui_state(current.observation.semantic_after).values.get(
                    "price"
                )
                if (
                    isinstance(updated_price, bool)
                    or not isinstance(updated_price, (int, float))
                    or Decimal(str(updated_price)) != ideal_price
                ):
                    raise SoftwareIncUIVerificationError(
                        "product price did not become the exact observed ideal price; "
                        "no retry attempted"
                    )
            gestures += 1
            continue
        price_text_selected = False
        design_teams = set(_product_ui_text(observation, "design_teams", empty=True).split("|"))
        development_teams = set(
            _product_ui_text(observation, "development_teams", empty=True).split("|")
        )
        design_teams.discard("")
        development_teams.discard("")
        missing_team_kind = (
            "design"
            if design_teams != {ATLAS_TEAM}
            else "development"
            if development_teams != {ATLAS_TEAM}
            else None
        )
        if missing_team_kind is not None:
            target_id = f"choose_product_{missing_team_kind}_team"
            if _has_target(observation, target_id):
                if dry_run:
                    return _result(
                        None, gestures, False, True, f"Dry run: would click {target_id}."
                    )
                current = await _click(
                    observer,
                    current,
                    _target(observation, target_id),
                    f"open exact {missing_team_kind} team selection",
                )
                gestures += 1
                if current.observation.scene is not SoftwareIncUIScene.PRODUCT_TEAM_SELECTION:
                    raise SoftwareIncUIVerificationError(
                        "product team picker did not open; no retry attempted"
                    )
                selecting_team = missing_team_kind
                continue
            if _has_target(observation, "product_next_page"):
                if dry_run:
                    return _result(
                        None,
                        gestures,
                        False,
                        True,
                        "Dry run: would open the next configuration page.",
                    )
                current = await _click(
                    observer,
                    current,
                    _target(observation, "product_next_page"),
                    "advance to the next reversible product configuration page",
                )
                gestures += 1
                if _product_ui_page(current.observation) == _product_ui_page(observation):
                    raise SoftwareIncUIVerificationError(
                        "next product page input did not change the observed page; "
                        "no retry attempted"
                    )
                continue
            raise SoftwareIncUIValidationError(
                f"exact {missing_team_kind} team selection is unavailable on the visible pages"
            )
        if selecting_team:
            raise SoftwareIncUIVerificationError(
                "team selection closed without changing the exact team"
            )
        selected_features = set(
            _product_ui_text(observation, "selected_features", empty=True).split("|")
        )
        selected_features.discard("")
        if selected_features != set(ATLAS_FEATURES):
            feature_by_name = {
                feature.name: feature
                for feature in product_features(observation.semantic_after, ATLAS_PRODUCT_TYPE)
            }
            target_name = next(
                iter(sorted(selected_features - set(ATLAS_FEATURES))),
                next(iter(sorted(set(ATLAS_FEATURES) - selected_features)), ""),
            )
            feature = feature_by_name.get(target_name)
            if (
                feature is None
                or not feature.unlocked
                or feature.dependencies
                or feature.server_requirement != 0
            ):
                raise SoftwareIncUIValidationError(
                    f"exact bounded {ATLAS_PRODUCT_TYPE} feature {target_name!r} is unavailable"
                )
            target_id = "product_feature_" + feature.feature_id.split(":", 1)[-1]
            if not _has_target(observation, target_id):
                if _has_target(observation, "product_previous_page"):
                    if dry_run:
                        return _result(
                            None,
                            gestures,
                            False,
                            True,
                            "Dry run: would return to the feature configuration page.",
                        )
                    current = await _click(
                        observer,
                        current,
                        _target(observation, "product_previous_page"),
                        "return to the reversible feature configuration page",
                    )
                    gestures += 1
                    if _product_ui_page(current.observation) == _product_ui_page(observation):
                        raise SoftwareIncUIVerificationError(
                            "previous product page input did not change the observed page; "
                            "no retry attempted"
                        )
                    continue
                raise SoftwareIncUIValidationError(
                    f"exact feature target for {target_name!r} is unavailable on visible pages"
                )
            if dry_run:
                return _result(
                    None,
                    gestures,
                    False,
                    True,
                    f"Dry run: would toggle bounded feature {target_name!r}.",
                )
            current = await _click(
                observer,
                current,
                _target(observation, target_id),
                f"toggle exact bounded dependency-free feature {target_name!r}",
            )
            gestures += 1
            updated_features = set(
                _product_ui_text(current.observation, "selected_features", empty=True).split("|")
            )
            updated_features.discard("")
            if updated_features != selected_features ^ {target_name}:
                raise SoftwareIncUIVerificationError(
                    "feature toggle did not produce the exact expected set; no retry attempted"
                )
            continue
        selected_operating_systems = set(
            _product_ui_text(observation, "selected_operating_systems", empty=True).split("|")
        )
        selected_operating_systems.discard("")
        options = operating_system_options(observation.semantic_after)
        if not options:
            raise SoftwareIncUIValidationError(
                "no exact available operating-system row is observed"
            )
        selected_os = options[0]
        expected_operating_system = f"{selected_os.product_id}:{selected_os.name}"
        if selected_operating_systems != {expected_operating_system}:
            extra_ids = [
                option.product_id
                for option in options
                if f"{option.product_id}:{option.name}" in selected_operating_systems
                and option.product_id != selected_os.product_id
            ]
            target_id = "product_os_" + (
                sorted(extra_ids)[0] if extra_ids else selected_os.product_id
            )
            if not _has_target(observation, target_id):
                if _has_target(observation, "product_previous_page"):
                    if dry_run:
                        return _result(
                            None,
                            gestures,
                            False,
                            True,
                            "Dry run: would return to the operating-system page.",
                        )
                    current = await _click(
                        observer,
                        current,
                        _target(observation, "product_previous_page"),
                        "return to the reversible operating-system page",
                    )
                    gestures += 1
                    if _product_ui_page(current.observation) == _product_ui_page(observation):
                        raise SoftwareIncUIVerificationError(
                            "previous product page input did not change the observed page; "
                            "no retry attempted"
                        )
                    continue
                raise SoftwareIncUIValidationError(
                    "exact operating-system target is unavailable on visible pages"
                )
            if dry_run:
                return _result(
                    None,
                    gestures,
                    False,
                    True,
                    f"Dry run: would set operating system {selected_os.name!r} with observed "
                    f"userbase {selected_os.userbase:,}.",
                )
            current = await _click(
                observer,
                current,
                _target(observation, target_id),
                f"set exact current operating system {selected_os.name!r} with the largest "
                "observed userbase",
            )
            gestures += 1
            toggled_operating_system = next(
                (
                    f"{option.product_id}:{option.name}"
                    for option in options
                    if option.product_id == target_id.removeprefix("product_os_")
                ),
                None,
            )
            if toggled_operating_system is None:
                raise SoftwareIncUIVerificationError(
                    "operating-system target no longer maps to an observed option"
                )
            updated_operating_systems = set(
                _product_ui_text(
                    current.observation, "selected_operating_systems", empty=True
                ).split("|")
            )
            updated_operating_systems.discard("")
            if updated_operating_systems != selected_operating_systems ^ {toggled_operating_system}:
                raise SoftwareIncUIVerificationError(
                    "operating-system toggle did not produce the exact expected set; "
                    "no retry attempted"
                )
            continue
        complete = all(
            (
                _product_ui_text(observation, "selected_category", empty=True),
                _product_ui_text(observation, "selected_features", empty=True),
                _product_ui_text(observation, "selected_operating_systems", empty=True),
            )
        )
        if not complete or not _has_target(observation, "commit_product_design"):
            if _has_target(observation, "product_next_page"):
                if dry_run:
                    return _result(
                        None, gestures, False, True, "Dry run: would inspect the next product page."
                    )
                current = await _click(
                    observer,
                    current,
                    _target(observation, "product_next_page"),
                    "inspect the next reversible product configuration page",
                )
                gestures += 1
                if _product_ui_page(current.observation) == _product_ui_page(observation):
                    raise SoftwareIncUIVerificationError(
                        "next product page input did not change the observed page; "
                        "no retry attempted"
                    )
                continue
            raise SoftwareIncUIValidationError(
                "feature, operating-system, or final design commitment state is incomplete"
            )
        recommendation = recommend_atlas(
            observation.semantic_after,
            minimum_cash_reserve=minimum_cash_reserve,
        )
        if not recommendation.recommended:
            return _result(
                None,
                gestures,
                True,
                True,
                "Atlas is not safe to create: " + "; ".join(recommendation.reasons),
                recommendation=recommendation,
            )
        workflow = create_workflow(observation.semantic_after, recommendation)
        approval = workflow.pending_approval
        assert approval is not None
        if dry_run:
            return _result(
                workflow,
                gestures,
                False,
                True,
                approval.action_summary,
                recommendation=recommendation,
            )
        repository.save(workflow)
        if approval_provider is None:
            return _result(
                workflow,
                gestures,
                False,
                True,
                approval.action_summary,
                recommendation=recommendation,
            )
        workflow = resolve_approval(workflow, approved=approval_provider(approval))
        if workflow.status is ProductWorkflowStatus.BLOCKED:
            workflow = workflow.model_copy(
                update={
                    "status": ProductWorkflowStatus.FAILED,
                    "updated_at": datetime.now(UTC),
                }
            )
            repository.save(workflow)
            return _result(
                workflow,
                gestures,
                False,
                False,
                "Atlas creation was denied; no commitment input sent.",
            )
        repository.save(workflow)
        refreshed = await observer.observe()
        _require_continuity(observation, refreshed.observation)
        _require_actionable(refreshed.observation)
        refreshed_recommendation = recommend_atlas(
            refreshed.observation.semantic_after,
            minimum_cash_reserve=minimum_cash_reserve,
        )
        if (
            not refreshed_recommendation.recommended
            or refreshed_recommendation.configuration != recommendation.configuration
            or refreshed_recommendation.runway != recommendation.runway
            or refreshed_recommendation.team != recommendation.team
        ):
            raise SoftwareIncUIValidationError(
                "Atlas configuration, runway, or team suitability changed during approval"
            )
        cash_before = current_cash(refreshed.observation.semantic_after)
        after = await _click(
            observer,
            refreshed,
            _target(refreshed.observation, "commit_product_design"),
            approval.action_summary,
        )
        gestures += 1
        if after.observation.modal_state is not ModalState.NONE:
            raise SoftwareIncUIVerificationError(
                "the game presented an unapproved product warning or charge; it was left untouched"
            )
        work = product_work(after.observation.semantic_after, "Atlas")
        if work is None or observed_stage(work) is not ProductStage.DESIGN:
            raise SoftwareIncUIVerificationError(
                "Atlas creation input did not produce one exact Design work item; "
                "no retry attempted"
            )
        cash_after = current_cash(after.observation.semantic_after)
        if cash_after < minimum_cash_reserve or cash_after > cash_before:
            raise SoftwareIncUIVerificationError(
                "Atlas creation cash outcome violated the approved reserve or increased "
                "unexpectedly"
            )
        workflow = synchronize_workflow(workflow, after.observation.semantic_after)
        repository.save(workflow)
        event = _append_event(
            repository,
            workflow,
            "product_created",
            ProductStage.CONFIGURATION,
            ProductStage.DESIGN,
            approval.action_summary,
            True,
            f"work_item_id={work.entity_id}; cash ${cash_before:,.2f} -> ${cash_after:,.2f}",
        )
        return _result(
            workflow,
            gestures,
            True,
            False,
            "Atlas design was created and verified; the game remains paused.",
            recommendation=recommendation,
            event=event,
        )
    raise SoftwareIncUIVerificationError("Atlas setup exceeded the bounded cycle limit")


async def set_product_hold(
    workflow: ProductWorkflow,
    *,
    held: bool,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ProductWorkflowStore | None = None,
) -> ProductOperationResult:
    repository = store or ProductWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    if not before.observation.paused:
        raise SoftwareIncUIValidationError("pause game time before changing Atlas hold state")
    current = synchronize_workflow(workflow, before.observation.semantic_after)
    if current.held == held:
        repository.save(current)
        return _result(
            current,
            0,
            True,
            False,
            f"Atlas is already {'held' if held else 'resumed'}; no input was sent.",
        )
    assert current.work_item_id is not None
    target_id = f"work-item-{current.work_item_id}-toggle-pause"
    before, opened = await _ensure_target(observer, before, target_id, dry_run=dry_run)
    if dry_run:
        return _result(
            current, opened, False, True, f"Dry run: would {'hold' if held else 'resume'} Atlas."
        )
    after = await _click(
        observer,
        before,
        _target(before.observation, target_id),
        f"{'hold' if held else 'resume'} Atlas work",
    )
    updated = synchronize_workflow(current, after.observation.semantic_after)
    if updated.held != held:
        raise SoftwareIncUIVerificationError(
            "Atlas hold input did not produce the exact pause state"
        )
    repository.save(updated)
    event = _append_event(
        repository,
        updated,
        "product_held" if held else "product_resumed",
        current.stage,
        updated.stage,
        f"{'hold' if held else 'resume'} exact Atlas work item",
        True,
        f"project_paused={updated.held}; game_paused=true",
    )
    return _result(
        updated,
        opened + 1,
        True,
        False,
        f"Atlas {'held' if held else 'resumed'} and verified.",
        event=event,
    )


async def advance_product(
    workflow: ProductWorkflow,
    *,
    run_seconds: float = 10.0,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ProductWorkflowStore | None = None,
) -> ProductOperationResult:
    if not 0 < run_seconds <= 30:
        raise SoftwareIncUIValidationError("product run interval must be between 0 and 30 seconds")
    repository = store or ProductWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    if not before.observation.paused:
        raise SoftwareIncUIValidationError("Atlas progression must begin from paused game time")
    current = synchronize_workflow(workflow, before.observation.semantic_after)
    if current.stage is ProductStage.BETA:
        repository.save(current)
        return _result(current, 0, True, False, "Atlas has reached beta; no time was advanced.")
    _require_reserve(current, before.observation.semantic_after)
    gestures = 0
    completed_review = _completed_review(before.observation.semantic_after, current.work_item_id)
    if completed_review is not None:
        target_id = f"work-item-{completed_review.entity_id}-finish-review"
        before, opened = await _ensure_target(observer, before, target_id, dry_run=dry_run)
        gestures += opened
        if dry_run:
            return _result(
                current,
                gestures,
                False,
                True,
                "Dry run: would finish the exact completed Atlas review.",
            )
        await _click(
            observer,
            before,
            _target(before.observation, target_id),
            "finish exact completed Atlas review",
        )
        return _result(
            current,
            gestures + 1,
            True,
            True,
            "Completed Atlas review opened; choose iterate or promote while paused.",
        )
    if current.held:
        assert current.work_item_id is not None
        target_id = f"work-item-{current.work_item_id}-toggle-pause"
        before, opened = await _ensure_target(observer, before, target_id, dry_run=dry_run)
        gestures += opened
        if dry_run:
            return _result(
                current, gestures, False, True, "Dry run: would resume Atlas project work."
            )
        before = await _click(
            observer,
            before,
            _target(before.observation, target_id),
            "resume exact Atlas project work",
        )
        gestures += 1
        current = synchronize_workflow(current, before.observation.semantic_after)
        if current.held:
            raise SoftwareIncUIVerificationError("Atlas project did not resume")
        repository.save(current)
    if before.observation.scene is not SoftwareIncUIScene.GAMEPLAY_PAUSED:
        if dry_run:
            return _result(
                current, gestures, False, True, "Dry run: would close reversible product UI."
            )
        before = await _key(
            observer,
            before,
            key_code=53,
            modifiers=(),
            target_id="escape_to_gameplay",
            effect="close reversible product UI",
        )
        gestures += 1
    if before.observation.scene is not SoftwareIncUIScene.GAMEPLAY_PAUSED:
        raise SoftwareIncUIVerificationError("product UI did not return to paused gameplay")
    if dry_run:
        return _result(
            current,
            gestures,
            False,
            True,
            f"Dry run: would run Atlas for {run_seconds:g}s and guarantee pause.",
        )
    running = await _click(
        observer, before, _target(before.observation, "resume_button"), "resume bounded Atlas work"
    )
    gestures += 1
    if running.observation.paused:
        raise SoftwareIncUIVerificationError("bounded Atlas progression did not resume game time")
    work_before = product_work(running.observation.semantic_after, current.product_name)
    try:
        await observer.keep_game_foreground()
        await asyncio.sleep(run_seconds)
    finally:
        paused, pause_gestures = await asyncio.shield(_pause_after_interval(observer))
        gestures += pause_gestures
    updated = synchronize_workflow(current, paused.observation.semantic_after)
    repository.save(updated)
    work_after = product_work(paused.observation.semantic_after, current.product_name)
    changed = (
        work_before is not None
        and work_after is not None
        and (
            work_before.values.get("progress") != work_after.values.get("progress")
            or observed_stage(work_before) is not observed_stage(work_after)
            or work_before.values.get("iteration") != work_after.values.get("iteration")
        )
    )
    event = _append_event(
        repository,
        updated,
        "product_advanced",
        current.stage,
        updated.stage,
        "bounded Atlas time progression",
        True,
        f"progress {current.progress}->{updated.progress}; game_paused=true",
    )
    return _result(
        updated,
        gestures,
        True,
        not changed,
        f"Atlas advanced for {run_seconds:g}s and is paused; progress "
        f"{current.progress}->{updated.progress}.",
        event=event,
    )


async def promote_product(
    workflow: ProductWorkflow,
    *,
    approval_provider: ApprovalProvider | None = None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ProductWorkflowStore | None = None,
) -> ProductOperationResult:
    repository = store or ProductWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    if not before.observation.paused:
        raise SoftwareIncUIValidationError("pause before an irreversible Atlas stage transition")
    current = synchronize_workflow(workflow, before.observation.semantic_after)
    if current.stage is ProductStage.BETA:
        return _result(
            current, 0, True, False, "Atlas is already in beta; release is outside Prompt 7."
        )
    projected = _require_reserve(current, before.observation.semantic_after)
    expected = ProductStage.ALPHA if current.stage is ProductStage.DESIGN else ProductStage.BETA
    pending = approval_for(
        current,
        ProductCommitment.PROMOTE,
        expected_stage=expected,
        observed_cash=current_cash(before.observation.semantic_after),
        projected_cash_after=projected,
    )
    current = current.model_copy(
        update={
            "pending_approval": pending,
            "status": ProductWorkflowStatus.WAITING_FOR_APPROVAL,
            "updated_at": datetime.now(UTC),
        }
    )
    if dry_run:
        return _result(current, 0, False, True, pending.action_summary)
    repository.save(current)
    if approval_provider is None:
        return _result(current, 0, False, True, pending.action_summary)
    current = resolve_approval(current, approved=approval_provider(pending))
    repository.save(current)
    if current.status is ProductWorkflowStatus.BLOCKED:
        return _result(current, 0, False, False, "Atlas promotion was denied; no input sent.")
    refreshed = await observer.observe()
    _require_continuity(before.observation, refreshed.observation)
    _require_actionable(refreshed.observation)
    synchronized = synchronize_workflow(current, refreshed.observation.semantic_after)
    if (
        synchronized.stage is not pending.stage_before
        or current_cash(refreshed.observation.semantic_after) != pending.observed_cash
        or _require_reserve(synchronized, refreshed.observation.semantic_after)
        != pending.projected_cash_after
    ):
        raise SoftwareIncUIValidationError(
            "Atlas stage or reserve changed during promotion approval"
        )
    assert synchronized.work_item_id is not None
    target_id = f"work-item-{synchronized.work_item_id}-promote"
    target = _optional_target(refreshed.observation, "review_result_promote") or _optional_target(
        refreshed.observation, target_id
    )
    gestures = 0
    if target is None:
        refreshed, opened = await _ensure_target(observer, refreshed, target_id, dry_run=False)
        gestures += opened
        target = _target(refreshed.observation, target_id)
    after = await _click(observer, refreshed, target, pending.action_summary)
    gestures += 1
    if after.observation.modal_state is ModalState.BLOCKING:
        confirmation = _target(after.observation, "confirm_dialog_yes")
        after = await _click(observer, after, confirmation, pending.action_summary)
        gestures += 1
    updated = synchronize_workflow(synchronized, after.observation.semantic_after)
    if updated.stage is not expected:
        raise SoftwareIncUIVerificationError(
            f"Atlas promotion did not reach {expected.value}; no retry attempted"
        )
    updated = updated.model_copy(update={"projected_cash_after": projected})
    repository.save(updated)
    event = _append_event(
        repository,
        updated,
        "product_promoted",
        synchronized.stage,
        updated.stage,
        pending.action_summary,
        True,
        f"stage={updated.stage.value}; projected_cash_after=${projected:,.2f}; game_paused=true",
    )
    return _result(
        updated,
        gestures,
        True,
        False,
        f"Atlas promoted to {updated.stage.value} and verified paused.",
        event=event,
    )


async def review_product(
    workflow: ProductWorkflow,
    *,
    approval_provider: ApprovalProvider | None = None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ProductWorkflowStore | None = None,
) -> ProductOperationResult:
    repository = store or ProductWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    if not before.observation.paused:
        raise SoftwareIncUIValidationError("pause before configuring an Atlas review")
    current = synchronize_workflow(workflow, before.observation.semantic_after)
    assert current.work_item_id is not None
    target_id = f"work-item-{current.work_item_id}-review"
    gestures = 0
    if before.observation.scene is not SoftwareIncUIScene.CONTRACT_REVIEW_SETUP:
        before, opened = await _ensure_target(observer, before, target_id, dry_run=dry_run)
        gestures += opened
        if dry_run:
            return _result(
                current, gestures, False, True, "Dry run: would open exact Atlas review setup."
            )
        before = await _click(
            observer,
            before,
            _target(before.observation, target_id),
            "open exact Atlas review setup",
        )
        gestures += 1
    if before.observation.scene is not SoftwareIncUIScene.CONTRACT_REVIEW_SETUP:
        raise SoftwareIncUIVerificationError("Atlas review setup did not open")
    cost = _review_cost(before.observation.semantic_after)
    cash = current_cash(before.observation.semantic_after)
    projected = _require_reserve(current, before.observation.semantic_after) - cost
    if projected < current.minimum_cash_reserve:
        raise SoftwareIncUIValidationError("Atlas review would violate the minimum cash reserve")
    pending = approval_for(
        current,
        ProductCommitment.REVIEW,
        expected_stage=current.stage,
        one_time_cost=cost,
        observed_cash=cash,
        projected_cash_after=projected,
    )
    current = current.model_copy(
        update={"pending_approval": pending, "status": ProductWorkflowStatus.WAITING_FOR_APPROVAL}
    )
    if dry_run:
        return _result(current, gestures, False, True, pending.action_summary)
    repository.save(current)
    if approval_provider is None:
        return _result(current, gestures, False, True, pending.action_summary)
    current = resolve_approval(current, approved=approval_provider(pending))
    repository.save(current)
    if current.status is ProductWorkflowStatus.BLOCKED:
        return _result(
            current, gestures, False, False, "Atlas review was denied; no review input sent."
        )
    refreshed = await observer.observe()
    _require_continuity(before.observation, refreshed.observation)
    if (
        refreshed.observation.scene is not SoftwareIncUIScene.CONTRACT_REVIEW_SETUP
        or _review_cost(refreshed.observation.semantic_after) != cost
        or current_cash(refreshed.observation.semantic_after) != pending.observed_cash
        or _require_reserve(current, refreshed.observation.semantic_after) - cost
        != pending.projected_cash_after
    ):
        raise SoftwareIncUIValidationError("Atlas review configuration changed during approval")
    after = await _click(
        observer,
        refreshed,
        _target(refreshed.observation, "commit_contract_review"),
        pending.action_summary,
    )
    gestures += 1
    if _linked_review(after.observation.semantic_after, current.work_item_id) is None:
        raise SoftwareIncUIVerificationError(
            "Atlas review commitment produced no linked review work"
        )
    review_cash_after = current_cash(after.observation.semantic_after)
    if review_cash_after != cash - cost:
        raise SoftwareIncUIVerificationError(
            "Atlas review cash outcome did not equal the exact approved cost"
        )
    updated = synchronize_workflow(current, after.observation.semantic_after)
    updated = updated.model_copy(update={"projected_cash_after": projected})
    repository.save(updated)
    event = _append_event(
        repository,
        updated,
        "product_review_started",
        current.stage,
        updated.stage,
        pending.action_summary,
        True,
        f"review_cost=${cost:,.2f}; cash ${cash:,.2f} -> ${review_cash_after:,.2f}",
    )
    return _result(updated, gestures, True, True, "Atlas review started and verified.", event=event)


async def iterate_product(
    workflow: ProductWorkflow,
    *,
    approval_provider: ApprovalProvider | None = None,
    dry_run: bool = False,
    observer_factory: ObserverFactory = SoftwareIncUIObserver,
    store: ProductWorkflowStore | None = None,
) -> ProductOperationResult:
    repository = store or ProductWorkflowStore()
    observer = observer_factory()
    before = await observer.observe()
    _require_actionable(before.observation)
    if (
        not before.observation.paused
        or before.observation.scene is not SoftwareIncUIScene.CONTRACT_REVIEW_RESULT
    ):
        raise SoftwareIncUIValidationError("iterate requires the exact paused Atlas review result")
    current = synchronize_workflow(workflow, before.observation.semantic_after)
    projected = _require_reserve(current, before.observation.semantic_after)
    pending = approval_for(
        current,
        ProductCommitment.ITERATE,
        expected_stage=current.stage,
        observed_cash=current_cash(before.observation.semantic_after),
        projected_cash_after=projected,
    )
    current = current.model_copy(
        update={"pending_approval": pending, "status": ProductWorkflowStatus.WAITING_FOR_APPROVAL}
    )
    if dry_run:
        return _result(current, 0, False, True, pending.action_summary)
    repository.save(current)
    if approval_provider is None:
        return _result(current, 0, False, True, pending.action_summary)
    current = resolve_approval(current, approved=approval_provider(pending))
    repository.save(current)
    if current.status is ProductWorkflowStatus.BLOCKED:
        return _result(current, 0, False, False, "Atlas iteration was denied; no input sent.")
    refreshed = await observer.observe()
    _require_continuity(before.observation, refreshed.observation)
    if (
        refreshed.observation.scene is not SoftwareIncUIScene.CONTRACT_REVIEW_RESULT
        or current_cash(refreshed.observation.semantic_after) != pending.observed_cash
        or _require_reserve(current, refreshed.observation.semantic_after)
        != pending.projected_cash_after
    ):
        raise SoftwareIncUIValidationError("Atlas review result changed during approval")
    after = await _click(
        observer,
        refreshed,
        _target(refreshed.observation, "review_result_iterate"),
        pending.action_summary,
    )
    updated = synchronize_workflow(current, after.observation.semantic_after)
    if updated.iteration <= workflow.iteration:
        raise SoftwareIncUIVerificationError(
            "Atlas iteration did not increase the observed iteration"
        )
    updated = updated.model_copy(update={"projected_cash_after": projected})
    repository.save(updated)
    event = _append_event(
        repository,
        updated,
        "product_iterated",
        current.stage,
        updated.stage,
        pending.action_summary,
        True,
        f"iteration {workflow.iteration}->{updated.iteration}",
    )
    return _result(
        updated,
        1,
        True,
        False,
        f"Atlas iteration {updated.iteration} started and verified.",
        event=event,
    )


async def _ensure_target(
    observer: ProductObserver,
    current: ObservedSoftwareIncUI,
    target_id: str,
    *,
    dry_run: bool,
) -> tuple[ObservedSoftwareIncUI, int]:
    if _optional_target(current.observation, target_id) is not None:
        return current, 0
    work_id = target_id.removeprefix("work-item-").split("-", 1)[0]
    card_id = f"work-item-{work_id}-open"
    if dry_run:
        _target(current.observation, card_id)
        return current, 0
    opened = await _click(
        observer,
        current,
        _target(current.observation, card_id),
        "open exact Atlas work-item controls",
    )
    if _optional_target(opened.observation, target_id) is None:
        raise SoftwareIncUIVerificationError(f"opening Atlas controls did not expose {target_id!r}")
    return opened, 1


async def _pause_after_interval(observer: ProductObserver) -> tuple[ObservedSoftwareIncUI, int]:
    current = await observer.observe()
    _require_actionable(current.observation)
    if current.observation.paused:
        return current, 0
    paused = await _click(
        observer,
        current,
        _target(current.observation, "pause_button"),
        "pause after bounded Atlas work",
    )
    if not paused.observation.paused:
        raise SoftwareIncUIVerificationError("bounded Atlas cleanup could not verify pause")
    return paused, 1


async def _click(
    observer: ProductObserver,
    before: ObservedSoftwareIncUI,
    target: VisualTarget,
    effect: str,
) -> ObservedSoftwareIncUI:
    if target.point is None:
        raise SoftwareIncUIValidationError("current-frame product target has no point")
    frame = before.observation.frame
    gesture = InputGesture(
        kind=InputGestureKind.CLICK,
        point=target.point,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=before.observation.scene.value,
        target_id=target.target_id,
        intended_effect=effect,
    )
    observer.backend.execute(gesture, frame=frame)  # type: ignore[attr-defined]
    await asyncio.sleep(_SETTLE_SECONDS)
    after = await observer.observe()
    _require_continuity(before.observation, after.observation)
    return after


async def _key(
    observer: ProductObserver,
    before: ObservedSoftwareIncUI,
    *,
    key_code: int,
    modifiers: tuple[KeyModifier, ...],
    target_id: str,
    effect: str,
) -> ObservedSoftwareIncUI:
    frame = before.observation.frame
    gesture = InputGesture(
        kind=InputGestureKind.KEY,
        key_code=key_code,
        modifiers=modifiers,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=before.observation.scene.value,
        target_id=target_id,
        intended_effect=effect,
    )
    observer.backend.execute(gesture, frame=frame)  # type: ignore[attr-defined]
    await asyncio.sleep(_SETTLE_SECONDS)
    after = await observer.observe()
    _require_continuity(before.observation, after.observation)
    return after


async def _text(
    observer: ProductObserver,
    before: ObservedSoftwareIncUI,
    value: str,
    target_id: str,
    effect: str,
) -> ObservedSoftwareIncUI:
    frame = before.observation.frame
    gesture = InputGesture(
        kind=InputGestureKind.TEXT,
        text=value,
        expected_process_id=frame.process_id,
        expected_window_id=frame.window_id,
        expected_window_bounds=frame.window_bounds,
        expected_frame_id=frame.frame_id,
        expected_scene=before.observation.scene.value,
        target_id=target_id,
        intended_effect=effect,
    )
    observer.backend.execute(gesture, frame=frame)  # type: ignore[attr-defined]
    await asyncio.sleep(_SETTLE_SECONDS)
    after = await observer.observe()
    _require_continuity(before.observation, after.observation)
    return after


def _target(observation: SoftwareIncUIObservation, target_id: str) -> VisualTarget:
    matches = [target for target in observation.targets if target.target_id == target_id]
    if len(matches) != 1:
        raise SoftwareIncUIValidationError(
            f"fresh target {target_id!r} did not resolve exactly once"
        )
    target = matches[0]
    if (
        target.confidence < 0.8
        or target.source_frame_id != observation.frame.frame_id
        or target.expires_at <= datetime.now(UTC)
    ):
        raise SoftwareIncUIValidationError("product target is stale or ambiguous")
    return target


def _product_ui_page(observation: SoftwareIncUIObservation) -> int:
    value = product_ui_state(observation.semantic_after).values.get("current_page")
    if isinstance(value, bool) or not isinstance(value, int):
        raise SoftwareIncUIValidationError("product_ui.current_page is not an observed integer")
    return value


def _optional_target(observation: SoftwareIncUIObservation, target_id: str) -> VisualTarget | None:
    matches = [target for target in observation.targets if target.target_id == target_id]
    if len(matches) > 1:
        raise SoftwareIncUIValidationError(f"product target {target_id!r} is ambiguous")
    return None if not matches else _target(observation, target_id)


def _has_target(observation: SoftwareIncUIObservation, target_id: str) -> bool:
    return _optional_target(observation, target_id) is not None


def _product_ui_text(
    observation: SoftwareIncUIObservation, field: str, *, empty: bool = False
) -> str:
    value = product_ui_state(observation.semantic_after).values.get(field)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise SoftwareIncUIValidationError(f"product_ui.{field} is not observed text")
    return value.strip()


def _require_actionable(observation: SoftwareIncUIObservation) -> None:
    if observation.modal_state is not ModalState.NONE:
        raise SoftwareIncUIObservationError(
            f"cannot operate Atlas while modal state is {observation.modal_state.value}"
        )
    if observation.scene in {SoftwareIncUIScene.UNKNOWN, SoftwareIncUIScene.BLOCKING_MODAL}:
        raise SoftwareIncUIObservationError(f"cannot operate Atlas from {observation.scene.value}")


def _require_continuity(before: SoftwareIncUIObservation, after: SoftwareIncUIObservation) -> None:
    left = before.semantic_after
    right = after.semantic_after
    if (
        left.bridge_instance_id != right.bridge_instance_id
        or left.game_session_id != right.game_session_id
        or left.save_identity != right.save_identity
        or right.bridge_sequence <= left.bridge_sequence
        or before.frame.process_id != after.frame.process_id
        or before.frame.window_id != after.frame.window_id
    ):
        raise SoftwareIncUIVerificationError(
            "Atlas save, session, bridge, window, or sequence changed"
        )


def _require_reserve(workflow: ProductWorkflow, snapshot: GameSnapshot) -> Decimal:
    cash = current_cash(snapshot)
    remaining_budget = max(Decimal("0"), workflow.initial_cash - workflow.projected_cash_after)
    projected = cash - remaining_budget
    if projected < workflow.minimum_cash_reserve:
        raise SoftwareIncUIValidationError(
            f"Atlas transition rejected: conservative projected cash ${projected:,.2f} is below "
            f"the ${workflow.minimum_cash_reserve:,.2f} reserve"
        )
    return projected


def _review_cost(snapshot: GameSnapshot) -> Decimal:
    values = [
        entity.values.get("review_cost_text")
        for surface in snapshot.surfaces
        if surface.coverage.surface == "contract_ui"
        for entity in surface.entities
        if entity.entity_type == "contract_ui_state" and entity.entity_id == "current"
    ]
    if len(values) != 1 or not isinstance(values[0], str):
        raise SoftwareIncUIValidationError("visible Atlas review cost is unavailable")
    matches = re.findall(r"\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", values[0])
    if not matches:
        if values[0].strip() in {"", "$0", "$0.00"}:
            return Decimal("0")
        raise SoftwareIncUIValidationError("visible Atlas review cost is not exact USD")
    return Decimal(matches[-1].replace(",", ""))


def _linked_review(snapshot: GameSnapshot, work_item_id: str | None) -> ObservedEntity | None:
    matches = [
        entity
        for surface in snapshot.surfaces
        if surface.coverage.surface == "work_items"
        for entity in surface.entities
        if entity.entity_type == "work_item"
        and entity.values.get("review_target_work_item_id") == work_item_id
    ]
    if len(matches) > 1:
        raise SoftwareIncUIValidationError("linked Atlas review work is ambiguous")
    return None if not matches else matches[0]


def _completed_review(snapshot: GameSnapshot, work_item_id: str | None) -> ObservedEntity | None:
    review = _linked_review(snapshot, work_item_id)
    if review is None:
        return None
    progress = review.values.get("progress")
    stage = str(review.values.get("stage", "")).casefold()
    return review if progress == 1.0 or "reviews finished" in stage else None


def _append_event(
    store: ProductWorkflowStore,
    workflow: ProductWorkflow,
    event_type: str,
    stage_before: ProductStage,
    stage_after: ProductStage,
    action: str | None,
    input_sent: bool,
    detail: str,
) -> ProductCycleEvent:
    event = ProductCycleEvent(
        event_id=uuid4(),
        workflow_id=workflow.workflow_id,
        sequence=len(store.events(workflow.workflow_id)) + 1,
        event_type=event_type,
        bridge_sequence=workflow.last_bridge_sequence,
        stage_before=stage_before,
        stage_after=stage_after,
        action=action,
        input_sent=input_sent,
        verified=True,
        detail=detail,
        recorded_at=datetime.now(UTC),
    )
    store.append_event(event)
    return event


def _existing_or_recovered_workflow(
    store: ProductWorkflowStore, snapshot: GameSnapshot, work: ObservedEntity
) -> ProductWorkflow:
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    existing = store.current(game_session_id=snapshot.game_session_id, save_identity=save_identity)
    if existing is None:
        raise SoftwareIncUIValidationError(
            "Atlas exists without a persisted Sim Pilot workflow; adopt/recovery is not authorized"
        )
    return (
        existing
        if existing.last_bridge_sequence == snapshot.bridge_sequence
        else synchronize_workflow(existing, snapshot)
    )


def _result(
    workflow: ProductWorkflow | None,
    gestures: int,
    verified: bool,
    partial: bool,
    message: str,
    *,
    recommendation: ProductRecommendation | None = None,
    event: ProductCycleEvent | None = None,
) -> ProductOperationResult:
    return ProductOperationResult(
        workflow=workflow,
        recommendation=recommendation,
        event=event,
        gestures_sent=gestures,
        verified=verified,
        partial=partial,
        message=message,
        completed_at=datetime.now(UTC),
    )


__all__ = [
    "advance_product",
    "close_product_configuration",
    "iterate_product",
    "promote_product",
    "review_product",
    "set_product_hold",
    "start_atlas",
]
