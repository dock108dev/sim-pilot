"""Opt-in live acceptance for the Software Inc. guided terminal experience."""

from __future__ import annotations

import asyncio
import os

import pytest

from sim_pilot.guidance import GuidanceStatus
from sim_pilot.software_inc.bridge.proof import save_fingerprint
from sim_pilot.software_inc.guidance import SoftwareIncGuidanceService

pytestmark = pytest.mark.live


@pytest.mark.skipif(
    os.environ.get("SIM_PILOT_LIVE_SOFTWARE_INC_GUIDANCE") != "1",
    reason=(
        "set SIM_PILOT_LIVE_SOFTWARE_INC_GUIDANCE=1 for the paused disposable-company "
        "guided-operator proof"
    ),
)
def test_live_guidance_reads_recommends_and_delegates_only_proven_ui() -> None:
    async def scenario() -> None:
        service = SoftwareIncGuidanceService()
        save_before = save_fingerprint()

        course = await service.crash_course("company")
        answer = await service.ask("How many employees do I have?")
        recommendation = await service.recommend()
        explanation = await service.explain(recommendation)
        phase4 = await service.operate(
            "Hire one programmer for Support Alpha for no more than $8,000 per month"
        )
        management = await service.operate("open manage teams")
        save_after = save_fingerprint()

        assert course.personalized is True
        assert answer.status is GuidanceStatus.ANSWERED
        assert recommendation.status is GuidanceStatus.ANSWERED
        assert explanation.status is GuidanceStatus.ANSWERED
        assert phase4.status is GuidanceStatus.BLOCKED
        assert phase4.gestures_sent == 0
        assert management.status is GuidanceStatus.COMPLETED
        assert management.verified is True
        assert management.gestures_sent <= 1
        assert save_after == save_before

    asyncio.run(scenario())
