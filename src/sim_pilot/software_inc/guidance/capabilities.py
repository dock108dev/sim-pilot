"""Unified, truthful Software Inc. guidance capability view."""

from __future__ import annotations

import hashlib
import json

from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.guidance import (
    CapabilityEvidenceStage,
    GuidedActionCapability,
    GuidedCapabilityView,
)
from sim_pilot.software_inc.bridge.models import SoftwareIncBridgeReport
from sim_pilot.software_inc.discovery.models import SoftwareIncDiscoveryResult
from sim_pilot.software_inc.ui.models import SoftwareIncUIAction
from sim_pilot.software_inc.ui.observer import LIVE_VERIFIED_ACTIONS

_EXPECTED_VERSION = "1.8.41"
_EXPECTED_BUILD = "23094975"
_PLATFORM = "macOS Steam 1.8.41 build 23094975 only; Windows and native ARM64 unverified"
_OFFLINE_STAFFING = (
    SoftwareIncUIAction.CREATE_TEAM,
    SoftwareIncUIAction.OBSERVE_APPLICANTS,
    SoftwareIncUIAction.HIRE_EMPLOYEE,
)
_OFFLINE_OFFICE = (
    SoftwareIncUIAction.SET_TEAM_WORKING_HOURS,
    SoftwareIncUIAction.ASSIGN_EMPLOYEE_ROLE,
    SoftwareIncUIAction.PREPARE_TEAM_WORKSTATION,
)
_OFFLINE_CONTRACTS = (
    SoftwareIncUIAction.OPEN_CONTRACTS,
    SoftwareIncUIAction.ACCEPT_CONTRACT,
    SoftwareIncUIAction.ADVANCE_CONTRACT,
    SoftwareIncUIAction.REVIEW_CONTRACT,
    SoftwareIncUIAction.PROMOTE_CONTRACT,
    SoftwareIncUIAction.RELEASE_CONTRACT,
)
_OFFLINE_TRAINING = (
    SoftwareIncUIAction.START_EDUCATION,
    SoftwareIncUIAction.ADVANCE_EDUCATION,
)
_OFFLINE_PRODUCTS = (
    SoftwareIncUIAction.CREATE_PRODUCT,
    SoftwareIncUIAction.ADVANCE_PRODUCT,
    SoftwareIncUIAction.REVIEW_PRODUCT,
    SoftwareIncUIAction.ITERATE_PRODUCT,
    SoftwareIncUIAction.PROMOTE_PRODUCT,
    SoftwareIncUIAction.HOLD_PRODUCT,
    SoftwareIncUIAction.RESUME_PRODUCT,
)


def guided_capability_view(
    discovery: SoftwareIncDiscoveryResult,
    *,
    snapshot: GameSnapshot | None,
    bridge_report: SoftwareIncBridgeReport | None,
    knowledge_topics: tuple[str, ...],
) -> GuidedCapabilityView:
    compatible_install = (
        discovery.product_version == _EXPECTED_VERSION
        and discovery.steam_build_id == _EXPECTED_BUILD
    )
    compatible_snapshot = snapshot is not None and (
        snapshot.game_id == "software-inc" and snapshot.game_version == _EXPECTED_VERSION
    )
    repository_bridge_loaded = bool(
        bridge_report
        and bridge_report.enabled
        and bridge_report.loaded
        and bridge_report.artifact_matches_installed is True
    )
    currently_compatible = compatible_install and compatible_snapshot and repository_bridge_loaded
    actions: list[GuidedActionCapability] = []
    for action in (
        SoftwareIncUIAction.PAUSE,
        SoftwareIncUIAction.RESUME,
        SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
    ):
        live = action in LIVE_VERIFIED_ACTIONS
        actions.append(
            GuidedActionCapability(
                action=action.value,
                direct_ui_action=True,
                offline_tested=True,
                live_verified=live,
                approval_required=False,
                evidence_stage=(
                    CapabilityEvidenceStage.LIVE_MUTATION_VERIFIED
                    if live
                    else CapabilityEvidenceStage.OFFLINE_INTEGRATION_TESTED
                ),
                compatible=currently_compatible,
                platform_boundary=_PLATFORM,
                reason=(
                    "historically live-proven; current window and scene preflight still required"
                    if currently_compatible
                    else "the exact live game, snapshot, and repository bridge are not current"
                ),
            )
        )
    for action in _OFFLINE_STAFFING:
        actions.append(
            GuidedActionCapability(
                action=action.value,
                direct_ui_action=True,
                offline_tested=True,
                live_verified=False,
                approval_required=True,
                evidence_stage=CapabilityEvidenceStage.OFFLINE_INTEGRATION_TESTED,
                compatible=currently_compatible,
                platform_boundary=_PLATFORM,
                reason="Phase 4 implementation exists, but its live mutation gate is pending",
            )
        )
    for action in _OFFLINE_OFFICE:
        live = action in LIVE_VERIFIED_ACTIONS
        actions.append(
            GuidedActionCapability(
                action=action.value,
                direct_ui_action=True,
                offline_tested=True,
                live_verified=live,
                approval_required=(action is SoftwareIncUIAction.PREPARE_TEAM_WORKSTATION),
                evidence_stage=(
                    CapabilityEvidenceStage.LIVE_MUTATION_VERIFIED
                    if live
                    else CapabilityEvidenceStage.OFFLINE_INTEGRATION_TESTED
                ),
                compatible=currently_compatible,
                platform_boundary=_PLATFORM,
                reason=(
                    "live-proven office UI workflow with exact semantic postcondition"
                    if live
                    else "Prompt 5 office workflow is offline-tested; live promotion is pending"
                ),
            )
        )
    for action in _OFFLINE_CONTRACTS:
        live = action in LIVE_VERIFIED_ACTIONS
        actions.append(
            GuidedActionCapability(
                action=action.value,
                direct_ui_action=True,
                offline_tested=True,
                live_verified=live,
                approval_required=(action is not SoftwareIncUIAction.OPEN_CONTRACTS),
                evidence_stage=(
                    CapabilityEvidenceStage.LIVE_MUTATION_VERIFIED
                    if live
                    else CapabilityEvidenceStage.OFFLINE_INTEGRATION_TESTED
                ),
                compatible=currently_compatible,
                platform_boundary=_PLATFORM,
                reason=(
                    "Prompt 6A contract-specific workflow is live-proven with exact semantic "
                    "postconditions"
                    if live
                    else "Prompt 6A contract-specific workflow is offline-tested; live "
                    "acceptance is still required"
                ),
            )
        )
    for action in _OFFLINE_TRAINING:
        live = action in LIVE_VERIFIED_ACTIONS
        actions.append(
            GuidedActionCapability(
                action=action.value,
                direct_ui_action=True,
                offline_tested=True,
                live_verified=live,
                approval_required=(action is SoftwareIncUIAction.START_EDUCATION),
                evidence_stage=(
                    CapabilityEvidenceStage.LIVE_MUTATION_VERIFIED
                    if live
                    else CapabilityEvidenceStage.OFFLINE_INTEGRATION_TESTED
                ),
                compatible=currently_compatible,
                platform_boundary=_PLATFORM,
                reason=(
                    "Prompt 6B exact employee, cost, active course, completion, and skill gain "
                    "are live-proven"
                    if live
                    else "Prompt 6B is offline-tested; live mutation acceptance is still required"
                ),
            )
        )
    for action in _OFFLINE_PRODUCTS:
        live = action in LIVE_VERIFIED_ACTIONS
        actions.append(
            GuidedActionCapability(
                action=action.value,
                direct_ui_action=True,
                offline_tested=True,
                live_verified=live,
                approval_required=action
                in {
                    SoftwareIncUIAction.CREATE_PRODUCT,
                    SoftwareIncUIAction.REVIEW_PRODUCT,
                    SoftwareIncUIAction.ITERATE_PRODUCT,
                    SoftwareIncUIAction.PROMOTE_PRODUCT,
                },
                evidence_stage=(
                    CapabilityEvidenceStage.LIVE_MUTATION_VERIFIED
                    if live
                    else CapabilityEvidenceStage.OFFLINE_INTEGRATION_TESTED
                ),
                compatible=currently_compatible,
                platform_boundary=_PLATFORM,
                reason=(
                    "Prompt 7 Atlas lifecycle is live-proven through beta"
                    if live
                    else "Prompt 7 Atlas lifecycle is offline-tested; live acceptance is pending"
                ),
            )
        )
    limitations: list[str] = [
        "The semantic bridge action catalog is empty.",
        "Software Inc. is not composed through the generic persisted-task runtime.",
    ]
    if snapshot is None:
        limitations.append("A compatible live semantic snapshot was unavailable.")
    if bridge_report is not None and bridge_report.artifact_matches_installed is False:
        limitations.append("The installed bridge DLL differs from the repository build artifact.")
    payload = {
        "game_version": discovery.product_version,
        "steam_build_id": discovery.steam_build_id,
        "observation_available": compatible_snapshot,
        "semantic_gameplay_actions": [],
        "generic_task_runtime_available": False,
        "actions": [
            item.model_dump(mode="json") for item in sorted(actions, key=lambda x: x.action)
        ],
        "knowledge_topics": knowledge_topics,
        "limitations": limitations,
    }
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return GuidedCapabilityView(
        game_id="software-inc",
        game_version=discovery.product_version,
        steam_build_id=discovery.steam_build_id,
        observation_available=compatible_snapshot,
        semantic_gameplay_actions=(),
        generic_task_runtime_available=False,
        actions=tuple(sorted(actions, key=lambda item: item.action)),
        knowledge_topics=knowledge_topics,
        capability_fingerprint=fingerprint,
        limitations=tuple(limitations),
    )


def action_capability(view: GuidedCapabilityView, action: str) -> GuidedActionCapability | None:
    return next((item for item in view.actions if item.action == action), None)


__all__ = ["action_capability", "guided_capability_view"]
