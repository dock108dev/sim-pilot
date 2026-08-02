"""Opt-in live acceptance for Prompt 5 read-only readiness and idempotence."""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

import pytest

from sim_pilot.guidance import GuidanceStatus
from sim_pilot.software_inc.bridge import software_inc_bridge_client
from sim_pilot.software_inc.bridge.proof import save_fingerprint
from sim_pilot.software_inc.guidance import SoftwareIncGuidanceService
from sim_pilot.software_inc.ui.models import SoftwareIncUIAction
from sim_pilot.software_inc.ui.office import OfficeIntent, project_team_readiness
from sim_pilot.software_inc.ui.office_controller import execute_office_intent

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_SOFTWARE_INC_OFFICE") != "1",
    reason=(
        "set SIM_PILOT_LIVE_SOFTWARE_INC_OFFICE=1 for the paused disposable-company "
        "office-readiness proof"
    ),
)
def test_live_office_readiness_questions_and_idempotent_schedule() -> None:
    async def scenario() -> None:
        client = software_inc_bridge_client()
        try:
            capabilities = await client.connect()
            snapshot = await client.request_full_snapshot()
        finally:
            await client.close()
        assert capabilities.gameplay_actions == ()
        speed = snapshot.game_state.get("simulation_speed")
        assert snapshot.game_state.get("force_pause") is True or speed in {"0", "0.0"}

        teams = next(
            surface for surface in snapshot.surfaces if surface.coverage.surface == "teams"
        )
        team_entities = [entity for entity in teams.entities if entity.entity_type == "team"]
        assert team_entities
        team = sorted(team_entities, key=lambda entity: entity.entity_id)[0]
        team_name = team.values["name"]
        assert isinstance(team_name, str)
        readiness = project_team_readiness(snapshot, team_name)
        assert readiness.required_capacity == readiness.employee_count
        assert readiness.current_capacity >= 0

        service = SoftwareIncGuidanceService()
        course = await service.crash_course("office")
        hours = await service.ask(f"What hours does {team_name} work?")
        capacity = await service.ask(f"Does {team_name} have enough desks?")
        server = await service.ask("Does this team need a server?")
        assert course.sections
        assert hours.status is GuidanceStatus.ANSWERED
        assert capacity.status is GuidanceStatus.ANSWERED
        assert server.status is GuidanceStatus.ANSWERED

        save_before = save_fingerprint()
        result = await execute_office_intent(
            OfficeIntent(
                action=SoftwareIncUIAction.SET_TEAM_WORKING_HOURS,
                team_name=team_name,
                work_start=Decimal(str(team.values["work_start"])),
                work_end=Decimal(str(team.values["work_end"])),
            )
        )
        save_after = save_fingerprint()
        assert result.verified
        assert result.gestures_sent == 0
        assert save_after == save_before

    asyncio.run(scenario())
