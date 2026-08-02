"""Synchronized semantic and exact-window observation for Software Inc."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from sim_pilot.computer_control.backend import CapturedDesktopFrame, ComputerControlBackend
from sim_pilot.computer_control.backends.macos import MacOSComputerControlBackend
from sim_pilot.computer_control.errors import ComputerControlError, StaleDesktopFrameError
from sim_pilot.game_bridge.models import (
    CapabilityManifestPayload,
    CoverageStatus,
    GameSnapshot,
)
from sim_pilot.software_inc.bridge.client import software_inc_bridge_client
from sim_pilot.software_inc.bridge.foreground import foreground_running_software_inc
from sim_pilot.software_inc.discovery import SoftwareIncDiscovery
from sim_pilot.software_inc.errors import SoftwareIncUIObservationError

from .models import (
    SoftwareIncUIAction,
    SoftwareIncUICapabilityCatalog,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
    UIActionCapability,
)
from .platform import normalize_software_inc_window, software_inc_window_identity
from .recognition import recognize_ui

_EXPECTED_VERSION = "1.8.41"
_EXPECTED_BUILD = "23094975"
_REQUIRED_SURFACES = (
    "applicants",
    "build_catalog",
    "build_ui",
    "company",
    "contract_market",
    "contract_results",
    "contract_ui",
    "education",
    "education_ui",
    "employees",
    "finances",
    "game_state",
    "infrastructure",
    "office_ui",
    "offices",
    "product_catalog",
    "product_ui",
    "products",
    "staffing_ui",
    "teams",
    "work_items",
)
_MAXIMUM_SYNCHRONIZATION_SECONDS = 10.0
_ACTIONABLE_FRAME_AGE_SECONDS = 1.0
_MAXIMUM_CAPTURE_REFRESHES = 2
_MAXIMUM_CAPTURE_ATTEMPTS = 2
LIVE_VERIFIED_ACTIONS: frozenset[SoftwareIncUIAction] = frozenset(
    {
        SoftwareIncUIAction.PAUSE,
        SoftwareIncUIAction.RESUME,
        SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
        SoftwareIncUIAction.OPEN_CONTRACTS,
        SoftwareIncUIAction.ACCEPT_CONTRACT,
        SoftwareIncUIAction.ADVANCE_CONTRACT,
        SoftwareIncUIAction.REVIEW_CONTRACT,
        SoftwareIncUIAction.PROMOTE_CONTRACT,
        SoftwareIncUIAction.RELEASE_CONTRACT,
        # Education is offline-tested until the exact v9 bridge and visible flow
        # complete the separately gated live acceptance.
    }
)


class BridgeObservationClient(Protocol):
    async def connect(self) -> CapabilityManifestPayload: ...

    async def request_full_snapshot(self) -> GameSnapshot: ...

    async def close(self) -> None: ...


class ObservedSoftwareIncUI:
    def __init__(
        self, observation: SoftwareIncUIObservation, capture: CapturedDesktopFrame
    ) -> None:
        self.observation = observation
        self.capture = capture


def software_inc_ui_backend() -> MacOSComputerControlBackend:
    return MacOSComputerControlBackend(
        "Software Inc",
        activator=foreground_running_software_inc,
        window_resolver=software_inc_window_identity,
        window_normalizer=normalize_software_inc_window,
    )


class SoftwareIncUIObserver:
    def __init__(
        self,
        *,
        backend: ComputerControlBackend | None = None,
        client_factory: Callable[[], BridgeObservationClient] = software_inc_bridge_client,
        discovery: SoftwareIncDiscovery | None = None,
    ) -> None:
        self.backend = backend or software_inc_ui_backend()
        self._client_factory = client_factory
        self._discovery = discovery or SoftwareIncDiscovery()

    async def observe(self) -> ObservedSoftwareIncUI:
        discovery = self._discovery.inspect()
        if (
            not discovery.live_supported
            or discovery.process_id is None
            or discovery.product_version != _EXPECTED_VERSION
            or discovery.steam_build_id != _EXPECTED_BUILD
        ):
            detail = "; ".join((*discovery.reasons, *discovery.warnings))
            raise SoftwareIncUIObservationError(
                detail or "exact live Software Inc. 1.8.41 build 23094975 is unavailable"
            )
        started = datetime.now(UTC)
        client = self._client_factory()
        try:
            manifest = await client.connect()
            if manifest.gameplay_actions:
                raise SoftwareIncUIObservationError(
                    "semantic bridge gameplay-action catalog must remain empty"
                )
            if manifest.observation_surfaces != _REQUIRED_SURFACES:
                raise SoftwareIncUIObservationError(
                    "semantic bridge observation-surface catalog changed"
                )
            before = await client.request_full_snapshot()
            capture = capture_with_retry(self.backend, process_id=discovery.process_id)
            after = await client.request_full_snapshot()
            for _attempt in range(_MAXIMUM_CAPTURE_REFRESHES):
                if capture.metadata.age_seconds(datetime.now(UTC)) <= _ACTIONABLE_FRAME_AGE_SECONDS:
                    break
                before = after
                capture = capture_with_retry(self.backend, process_id=discovery.process_id)
                after = await client.request_full_snapshot()
        finally:
            await client.close()
        completed = datetime.now(UTC)
        require_ui_continuity(before, after, capture)
        duration = (completed - started).total_seconds()
        if duration > _MAXIMUM_SYNCHRONIZATION_SECONDS:
            raise SoftwareIncUIObservationError("synchronized observation exceeded time bound")
        skew = max(
            abs((capture.metadata.captured_at - before.capture_timestamp).total_seconds()),
            abs((after.capture_timestamp - capture.metadata.captured_at).total_seconds()),
        )
        if skew > _MAXIMUM_SYNCHRONIZATION_SECONDS:
            raise SoftwareIncUIObservationError("screenshot and semantic capture skew is excessive")
        paused = _paused(after)
        scene, modal, projection_id, targets = recognize_ui(
            capture,
            snapshot=after,
            paused=paused,
        )
        observation = SoftwareIncUIObservation(
            semantic_before=before,
            semantic_after=after,
            frame=capture.metadata,
            scene=scene,
            modal_state=modal,
            projection_id=projection_id,
            targets=targets,
            synchronization_started_at=started,
            synchronization_completed_at=completed,
            synchronization_duration_seconds=duration,
            semantic_capture_skew_seconds=skew,
        )
        return ObservedSoftwareIncUI(observation, capture)

    async def keep_game_foreground(self) -> None:
        """Keep Unity active during an intentionally bounded real-time interval."""
        await asyncio.to_thread(foreground_running_software_inc)

    async def capabilities(self) -> SoftwareIncUICapabilityCatalog:
        observed = await self.observe()
        scene = observed.observation.scene
        targets = {target.target_id for target in observed.observation.targets}
        gameplay_scene = scene in {
            SoftwareIncUIScene.GAMEPLAY_PAUSED,
            SoftwareIncUIScene.GAMEPLAY_RUNNING,
        }
        management_open = scene is SoftwareIncUIScene.MANAGE_TEAMS
        platform = "macOS Steam 1.8.41 build 23094975 only; Windows unverified"
        return SoftwareIncUICapabilityCatalog(
            capabilities=(
                UIActionCapability(
                    action=SoftwareIncUIAction.PAUSE,
                    supported=gameplay_scene,
                    offline_tested=True,
                    live_verified=SoftwareIncUIAction.PAUSE in LIVE_VERIFIED_ACTIONS,
                    starting_scenes=(SoftwareIncUIScene.GAMEPLAY_RUNNING,),
                    gesture_types=("click",),
                    semantic_postcondition="force_pause=true or simulation_speed=0",
                    visual_postcondition="fresh frame remains recognized gameplay_paused",
                    platform_boundary=platform,
                    reason=(
                        "verified gameplay scene and synchronized semantic state"
                        if gameplay_scene
                        else f"current scene is {scene.value}"
                    ),
                ),
                UIActionCapability(
                    action=SoftwareIncUIAction.RESUME,
                    supported=gameplay_scene,
                    offline_tested=True,
                    live_verified=SoftwareIncUIAction.RESUME in LIVE_VERIFIED_ACTIONS,
                    starting_scenes=(SoftwareIncUIScene.GAMEPLAY_PAUSED,),
                    gesture_types=("click",),
                    semantic_postcondition="force_pause=false and simulation_speed is non-zero",
                    visual_postcondition="fresh frame remains recognized gameplay_running",
                    platform_boundary=platform,
                    reason=(
                        "verified gameplay scene and synchronized semantic state"
                        if gameplay_scene
                        else f"current scene is {scene.value}"
                    ),
                ),
                UIActionCapability(
                    action=SoftwareIncUIAction.OPEN_MANAGE_TEAMS,
                    supported=management_open
                    or (gameplay_scene and "manage_teams_button" in targets),
                    offline_tested=True,
                    live_verified=SoftwareIncUIAction.OPEN_MANAGE_TEAMS in LIVE_VERIFIED_ACTIONS,
                    starting_scenes=(
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                    ),
                    gesture_types=("click",),
                    semantic_postcondition="no gameplay-semantic entity mutation",
                    visual_postcondition=(
                        "fresh frame recognized as manage_teams; a first-use tutorial modal "
                        "is reported as blocking and left untouched"
                    ),
                    platform_boundary=platform,
                    reason=(
                        "Manage Teams is already visibly open"
                        if management_open
                        else "current-frame management toolbar target resolved"
                        if gameplay_scene and "manage_teams_button" in targets
                        else "management toolbar target is unavailable"
                    ),
                ),
                UIActionCapability(
                    action=SoftwareIncUIAction.CREATE_TEAM,
                    supported=scene
                    in {
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                        SoftwareIncUIScene.CREATE_TEAM_FORM,
                    },
                    offline_tested=True,
                    live_verified=SoftwareIncUIAction.CREATE_TEAM in LIVE_VERIFIED_ACTIONS,
                    starting_scenes=(
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                    ),
                    gesture_types=("click", "text"),
                    semantic_postcondition="exactly one uniquely named team added",
                    visual_postcondition="fresh staffing scene and field value after every gesture",
                    platform_boundary=platform,
                    reason="approval is required immediately before the create commitment",
                ),
                UIActionCapability(
                    action=SoftwareIncUIAction.OBSERVE_APPLICANTS,
                    supported=scene
                    in {
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                        SoftwareIncUIScene.HIRING_SETUP,
                        SoftwareIncUIScene.APPLICANT_LIST,
                    },
                    offline_tested=True,
                    live_verified=(SoftwareIncUIAction.OBSERVE_APPLICANTS in LIVE_VERIFIED_ACTIONS),
                    starting_scenes=(
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                    ),
                    gesture_types=("click",),
                    semantic_postcondition=(
                        "approved one-time search cost charged exactly and complete visible "
                        "applicant identities observed"
                    ),
                    visual_postcondition="fresh applicant-list scene",
                    platform_boundary=platform,
                    reason="paid search and applicant list are separately observed",
                ),
                UIActionCapability(
                    action=SoftwareIncUIAction.HIRE_EMPLOYEE,
                    supported=scene
                    in {
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                        SoftwareIncUIScene.HIRING_SETUP,
                        SoftwareIncUIScene.APPLICANT_LIST,
                    },
                    offline_tested=True,
                    live_verified=SoftwareIncUIAction.HIRE_EMPLOYEE in LIVE_VERIFIED_ACTIONS,
                    starting_scenes=(
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                        SoftwareIncUIScene.APPLICANT_LIST,
                    ),
                    gesture_types=("click",),
                    semantic_postcondition=(
                        "exactly one approved programmer added to the target team; observed "
                        "salary and recurring payroll delta remain within the user cap"
                    ),
                    visual_postcondition="fresh post-hire UI scene",
                    platform_boundary=platform,
                    reason="candidate identity and monthly salary require exact approval",
                ),
                UIActionCapability(
                    action=SoftwareIncUIAction.SET_TEAM_WORKING_HOURS,
                    supported=scene
                    in {
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                    },
                    offline_tested=True,
                    live_verified=(
                        SoftwareIncUIAction.SET_TEAM_WORKING_HOURS in LIVE_VERIFIED_ACTIONS
                    ),
                    starting_scenes=(
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                    ),
                    gesture_types=("click", "key", "text"),
                    semantic_postcondition="exact team work_start and work_end",
                    visual_postcondition="fresh selected team and exact visible schedule fields",
                    platform_boundary=platform,
                    reason="whole-hour schedule workflow is bounded and keeps the game paused",
                ),
                UIActionCapability(
                    action=SoftwareIncUIAction.ASSIGN_EMPLOYEE_ROLE,
                    supported=scene
                    in {
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                        SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
                        SoftwareIncUIScene.ROLE_SELECTION,
                    },
                    offline_tested=True,
                    live_verified=(
                        SoftwareIncUIAction.ASSIGN_EMPLOYEE_ROLE in LIVE_VERIFIED_ACTIONS
                    ),
                    starting_scenes=(
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.MANAGE_TEAMS,
                    ),
                    gesture_types=("click",),
                    semantic_postcondition="exact employee identity includes the requested role",
                    visual_postcondition="fresh employee and role selection after every click",
                    platform_boundary=platform,
                    reason="one exact employee, team, and supported role are required",
                ),
                UIActionCapability(
                    action=SoftwareIncUIAction.PREPARE_TEAM_WORKSTATION,
                    supported=scene
                    in {
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                        SoftwareIncUIScene.BUILD_MODE,
                        SoftwareIncUIScene.BUILD_SEARCH,
                        SoftwareIncUIScene.FURNITURE_PLACEMENT,
                        SoftwareIncUIScene.ROOM_CONTEXT_MENU,
                        SoftwareIncUIScene.ROOM_TEAM_SELECTION,
                    },
                    offline_tested=True,
                    live_verified=(
                        SoftwareIncUIAction.PREPARE_TEAM_WORKSTATION in LIVE_VERIFIED_ACTIONS
                    ),
                    starting_scenes=(
                        SoftwareIncUIScene.GAMEPLAY_PAUSED,
                        SoftwareIncUIScene.GAMEPLAY_RUNNING,
                    ),
                    gesture_types=("click", "right_click", "move", "key", "text"),
                    semantic_postcondition=(
                        "exact room assignment, one valid workstation, and exact cash delta"
                    ),
                    visual_postcondition=(
                        "fresh catalog search, green placement preview, and post-placement frame"
                    ),
                    platform_boundary=platform,
                    reason="exact itemized approval is required before any furniture commitment",
                ),
                *(
                    UIActionCapability(
                        action=action,
                        supported=(
                            scene
                            in {
                                SoftwareIncUIScene.GAMEPLAY_PAUSED,
                                SoftwareIncUIScene.GAMEPLAY_RUNNING,
                                SoftwareIncUIScene.CONTRACT_BROWSER,
                                SoftwareIncUIScene.CONTRACT_TEAM_SELECTION,
                                SoftwareIncUIScene.CONTRACT_REVIEW_SETUP,
                                SoftwareIncUIScene.CONTRACT_REVIEW_RESULT,
                            }
                        ),
                        offline_tested=True,
                        live_verified=action in LIVE_VERIFIED_ACTIONS,
                        starting_scenes=(
                            SoftwareIncUIScene.GAMEPLAY_PAUSED,
                            SoftwareIncUIScene.GAMEPLAY_RUNNING,
                            SoftwareIncUIScene.CONTRACT_BROWSER,
                        ),
                        gesture_types=("click",),
                        semantic_postcondition=(
                            "fresh contract market, work-item stage, or result state"
                        ),
                        visual_postcondition=(
                            "fresh visible contract or work-item control after every gesture"
                        ),
                        platform_boundary=platform,
                        reason=(
                            "Prompt 6A contract workflow is live-proven; every irreversible "
                            "commitment still requires separate approval"
                            if action in LIVE_VERIFIED_ACTIONS
                            else "Prompt 6A contract workflow is offline-tested; every "
                            "irreversible commitment requires separate approval"
                        ),
                    )
                    for action in (
                        SoftwareIncUIAction.OPEN_CONTRACTS,
                        SoftwareIncUIAction.ACCEPT_CONTRACT,
                        SoftwareIncUIAction.ADVANCE_CONTRACT,
                        SoftwareIncUIAction.REVIEW_CONTRACT,
                        SoftwareIncUIAction.PROMOTE_CONTRACT,
                        SoftwareIncUIAction.RELEASE_CONTRACT,
                    )
                ),
                *(
                    UIActionCapability(
                        action=action,
                        supported=scene
                        in {
                            SoftwareIncUIScene.GAMEPLAY_PAUSED,
                            SoftwareIncUIScene.GAMEPLAY_RUNNING,
                            SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
                            SoftwareIncUIScene.EDUCATION,
                        },
                        offline_tested=True,
                        live_verified=action in LIVE_VERIFIED_ACTIONS,
                        starting_scenes=(
                            SoftwareIncUIScene.GAMEPLAY_PAUSED,
                            SoftwareIncUIScene.GAMEPLAY_RUNNING,
                            SoftwareIncUIScene.EMPLOYEE_MANAGEMENT,
                            SoftwareIncUIScene.EDUCATION,
                        ),
                        gesture_types=("click", "key"),
                        semantic_postcondition=(
                            "exact employee Designer:System course and cost on start; exact "
                            "course completion and increased specialization after progression"
                        ),
                        visual_postcondition=(
                            "fresh Education UI after each configuration gesture and paused "
                            "gameplay after every bounded progression interval"
                        ),
                        platform_boundary=platform,
                        reason=(
                            "Prompt 6B education workflow is live-proven"
                            if action in LIVE_VERIFIED_ACTIONS
                            else "Prompt 6B education workflow is offline-tested; exact spending "
                            "approval and live acceptance remain required"
                        ),
                    )
                    for action in (
                        SoftwareIncUIAction.START_EDUCATION,
                        SoftwareIncUIAction.ADVANCE_EDUCATION,
                    )
                ),
            )
        )


def capture_with_retry(
    backend: ComputerControlBackend,
    *,
    process_id: int,
) -> CapturedDesktopFrame:
    """Retry one read-only capture race; never retry an input gesture."""
    for attempt in range(_MAXIMUM_CAPTURE_ATTEMPTS):
        try:
            return backend.capture(process_id=process_id)
        except (ComputerControlError, StaleDesktopFrameError):
            if attempt + 1 == _MAXIMUM_CAPTURE_ATTEMPTS:
                raise
    raise AssertionError("capture retry loop did not return or raise")


def _paused(snapshot: GameSnapshot) -> bool:
    state = snapshot.game_state
    return state.get("force_pause") is True or state.get("simulation_speed") in {"0", "0.0"}


def require_ui_continuity(
    before: GameSnapshot,
    after: GameSnapshot,
    capture: CapturedDesktopFrame,
) -> None:
    if (
        before.bridge_instance_id != after.bridge_instance_id
        or before.game_session_id != after.game_session_id
        or before.map_identity != after.map_identity
        or before.save_identity != after.save_identity
        or before.game_id != "software-inc"
        or after.game_id != "software-inc"
        or before.game_version != _EXPECTED_VERSION
        or after.game_version != _EXPECTED_VERSION
        or after.bridge_sequence <= before.bridge_sequence
    ):
        raise SoftwareIncUIObservationError(
            "bridge, session, save, game, or sequence identity changed during observation"
        )
    if capture.metadata.process_id < 1 or not capture.metadata.window_frontmost:
        raise SoftwareIncUIObservationError("exact game process/window was not captured frontmost")
    observed = tuple(surface.coverage.surface for surface in after.surfaces)
    if observed != _REQUIRED_SURFACES:
        raise SoftwareIncUIObservationError("required semantic surfaces are unavailable")
    for surface in after.surfaces:
        if (
            surface.coverage.surface in {"applicants", "contract_market"}
            and surface.coverage.status is CoverageStatus.UNAVAILABLE
        ):
            continue
        if surface.coverage.status in {
            CoverageStatus.UNAVAILABLE,
            CoverageStatus.FAILED,
            CoverageStatus.UNSUPPORTED,
        }:
            raise SoftwareIncUIObservationError(
                f"semantic surface {surface.coverage.surface} is {surface.coverage.status.value}"
            )


__all__ = [
    "LIVE_VERIFIED_ACTIONS",
    "ObservedSoftwareIncUI",
    "SoftwareIncUIObserver",
    "require_ui_continuity",
    "software_inc_ui_backend",
]
