"""Deterministic Software Inc. guidance fixtures."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from sim_pilot.game_bridge import (
    Architecture,
    CoverageStatus,
    FieldCoverage,
    GameSnapshot,
    Identity,
    IdentityStatus,
    ObservationSurface,
    ObservedEntity,
    Platform,
)
from sim_pilot.software_inc.bridge.models import SoftwareIncBridgeReport
from sim_pilot.software_inc.discovery.models import (
    Distribution,
    ScriptingBackend,
    SoftwareIncDiscoveryResult,
)
from sim_pilot.software_inc.guidance.capabilities import guided_capability_view
from sim_pilot.software_inc.guidance.context import SoftwareIncGuidanceContext
from sim_pilot.software_inc.guidance.knowledge import SoftwareIncKnowledgeProvider
from sim_pilot.software_inc.guidance.state import project_state
from sim_pilot.software_inc.ui.models import (
    ModalState,
    SoftwareIncUIObservation,
    SoftwareIncUIScene,
)
from tests.software_inc.test_ui_control import capture_fixture


def discovery(*, running: bool = True, version: str = "1.8.41") -> SoftwareIncDiscoveryResult:
    return SoftwareIncDiscoveryResult(
        distribution=Distribution.STEAM,
        installed=True,
        game_root=Path("/fixture/Software Inc"),
        product_version=version,
        steam_build_id="23094975",
        executable_architectures=("x86_64",),
        running_architecture="x86_64" if running else None,
        unity_version="2018.4.36f1",
        scripting_backend=ScriptingBackend.MONO,
        official_code_mod_api_observed=True,
        running=running,
        process_id=77 if running else None,
        probe_source_available=True,
        probe_installed=True,
        probe_enabled=True,
        probe_loaded=running,
        compatible=True,
        live_supported=running,
        reasons=(),
        coverage=(),
    )


def surface(
    name: str,
    entities: tuple[ObservedEntity, ...] = (),
    *,
    status: CoverageStatus = CoverageStatus.OBSERVED_COMPLETE,
) -> ObservationSurface:
    return ObservationSurface(
        coverage=FieldCoverage(surface=name, status=status, fields=()),
        entities=entities,
    )


def snapshot(
    *,
    paused: bool = True,
    session: str = "session-1",
    save: str = "beginner-save",
    complete_teams: bool = True,
    complete_employees: bool = True,
    empty_support_team: bool = True,
) -> GameSnapshot:
    teams = (
        ObservedEntity(
            entity_type="team",
            entity_id="core",
            values={"name": "Core", "employee_count": 1, "work_start": 8, "work_end": 16},
        ),
        ObservedEntity(
            entity_type="team",
            entity_id="support-alpha",
            values={
                "name": "Support Alpha",
                "employee_count": 0 if empty_support_team else 1,
                "work_start": 8,
                "work_end": 16,
            },
        ),
    )
    employees = [
        ObservedEntity(
            entity_type="employee",
            entity_id="founder",
            values={
                "name": "Founder",
                "role": "Founder",
                "team": "Core",
                "salary": 0,
                "founder": True,
            },
        )
    ]
    if not empty_support_team:
        employees.append(
            ObservedEntity(
                entity_type="employee",
                entity_id="programmer-1",
                values={
                    "name": "Ada",
                    "role": "Programmer",
                    "team": "Support Alpha",
                    "salary": 6200,
                    "founder": False,
                },
            )
        )
    return GameSnapshot(
        capture_timestamp=datetime.now(UTC),
        capture_started_marker="main-thread",
        capture_completed_marker="main-thread",
        bridge_sequence=7,
        bridge_instance_id="bridge-1",
        game_session_id=session,
        game_id="software-inc",
        game_version="1.8.41",
        adapter_version="software-inc-readonly-v5",
        platform=Platform.MACOS,
        architecture=Architecture.X86_64,
        map_identity=Identity(status=IdentityStatus.UNAVAILABLE, detail="not applicable"),
        save_identity=Identity(status=IdentityStatus.OBSERVED, value=save),
        game_state={
            "force_pause": paused,
            "simulation_speed": "0" if paused else "1",
        },
        surfaces=tuple(
            sorted(
                (
                    surface("applicants"),
                    surface(
                        "company",
                        (
                            ObservedEntity(
                                entity_type="company",
                                entity_id="company",
                                values={"name": "Fixture Labs"},
                            ),
                        ),
                    ),
                    surface("contract_market"),
                    surface("contract_results"),
                    surface("contract_ui"),
                    surface(
                        "employees",
                        tuple(employees),
                        status=(
                            CoverageStatus.OBSERVED_COMPLETE
                            if complete_employees
                            else CoverageStatus.OBSERVED_PARTIAL
                        ),
                    ),
                    surface(
                        "finances",
                        (
                            ObservedEntity(
                                entity_type="company_finances",
                                entity_id="company",
                                values={"cash": 100_000, "valuation": 150_000},
                            ),
                        ),
                        status=CoverageStatus.OBSERVED_PARTIAL,
                    ),
                    surface("game_state"),
                    surface("infrastructure"),
                    surface("office_ui"),
                    surface(
                        "offices",
                        (
                            ObservedEntity(
                                entity_type="office_room",
                                entity_id="room-core",
                                values={
                                    "floor": 0,
                                    "assigned_teams": "Core",
                                    "assignable_workstations": 1,
                                    "valid_workstations": 1,
                                    "available_workstations": 0,
                                    "total_furniture": 1,
                                    "major_problem": False,
                                    "problem_count": 0,
                                    "is_lit": True,
                                    "environment": 1,
                                    "temperature": 21,
                                    "acoustics": 0.5,
                                },
                            ),
                        ),
                    ),
                    surface("products", status=CoverageStatus.OBSERVED_PARTIAL),
                    surface("staffing_ui"),
                    surface(
                        "teams",
                        teams,
                        status=(
                            CoverageStatus.OBSERVED_COMPLETE
                            if complete_teams
                            else CoverageStatus.OBSERVED_PARTIAL
                        ),
                    ),
                    surface("work_items", status=CoverageStatus.OBSERVED_PARTIAL),
                ),
                key=lambda item: item.coverage.surface,
            )
        ),
    )


def guidance_context(
    *,
    live_state: bool = True,
    artifact_matches: bool = True,
    paused: bool = True,
    session: str = "session-1",
    save: str = "beginner-save",
    complete_teams: bool = True,
    complete_employees: bool = True,
    empty_support_team: bool = True,
) -> SoftwareIncGuidanceContext:
    observed_discovery = discovery(running=live_state)
    observed_snapshot = (
        snapshot(
            paused=paused,
            session=session,
            save=save,
            complete_teams=complete_teams,
            complete_employees=complete_employees,
            empty_support_team=empty_support_team,
        )
        if live_state
        else None
    )
    bridge_report = SoftwareIncBridgeReport(
        discovery=observed_discovery,
        artifact=Path("/fixture/repository.dll"),
        artifact_available=True,
        artifact_sha256="a" * 64,
        installed_sha256=("a" if artifact_matches else "b") * 64,
        artifact_matches_installed=artifact_matches,
        manifest_path=Path("/fixture/manifest.json"),
        installed=True,
        enabled=True,
        loaded=live_state,
    )
    provider = SoftwareIncKnowledgeProvider()
    capabilities = guided_capability_view(
        observed_discovery,
        snapshot=observed_snapshot,
        bridge_report=bridge_report,
        knowledge_topics=provider.topics(),
    )
    return SoftwareIncGuidanceContext(
        discovery=observed_discovery,
        bridge_report=bridge_report,
        snapshot=observed_snapshot,
        state=project_state(observed_snapshot) if observed_snapshot is not None else None,
        snapshot_error=None if live_state else "Software Inc. is not running",
        capabilities=capabilities,
    )


def ui_observation(
    *, scene: SoftwareIncUIScene = SoftwareIncUIScene.MANAGE_TEAMS
) -> SoftwareIncUIObservation:
    semantic = snapshot()
    now = datetime.now(UTC)
    frame = capture_fixture(Image.new("RGB", (1200, 800)), sequence=1).metadata
    return SoftwareIncUIObservation(
        semantic_before=semantic,
        semantic_after=semantic,
        frame=frame,
        scene=scene,
        modal_state=ModalState.NONE,
        projection_id="a" * 64,
        targets=(),
        synchronization_started_at=now,
        synchronization_completed_at=now,
        synchronization_duration_seconds=0,
        semantic_capture_skew_seconds=0,
    )


__all__ = ["discovery", "guidance_context", "snapshot", "surface", "ui_observation"]
