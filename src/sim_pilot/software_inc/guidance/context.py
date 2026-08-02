"""Read-only Software Inc. guidance context composition."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.guidance import GuidedCapabilityView
from sim_pilot.software_inc.bridge import software_inc_bridge_client
from sim_pilot.software_inc.bridge.installer import SoftwareIncBridgeInstaller
from sim_pilot.software_inc.bridge.models import SoftwareIncBridgeReport
from sim_pilot.software_inc.discovery import SoftwareIncDiscovery
from sim_pilot.software_inc.discovery.models import SoftwareIncDiscoveryResult

from .capabilities import guided_capability_view
from .knowledge import SoftwareIncKnowledgeProvider
from .state import SoftwareIncStateView, project_state

type SnapshotLoader = Callable[[], Awaitable[GameSnapshot]]


@dataclass(frozen=True)
class SoftwareIncGuidanceContext:
    discovery: SoftwareIncDiscoveryResult
    bridge_report: SoftwareIncBridgeReport | None
    snapshot: GameSnapshot | None
    state: SoftwareIncStateView | None
    snapshot_error: str | None
    capabilities: GuidedCapabilityView


async def collect_snapshot() -> GameSnapshot:
    client = software_inc_bridge_client()
    try:
        manifest = await client.connect()
        if manifest.gameplay_actions:
            raise RuntimeError("semantic bridge unexpectedly advertised gameplay actions")
        return await client.request_full_snapshot()
    finally:
        await client.close()


class SoftwareIncGuidanceContextProvider:
    def __init__(
        self,
        *,
        discovery: SoftwareIncDiscovery | None = None,
        bridge_installer: SoftwareIncBridgeInstaller | None = None,
        knowledge: SoftwareIncKnowledgeProvider | None = None,
        snapshot_loader: SnapshotLoader = collect_snapshot,
    ) -> None:
        self._discovery = discovery or SoftwareIncDiscovery()
        self._bridge_installer = bridge_installer or SoftwareIncBridgeInstaller(
            discovery=self._discovery
        )
        self.knowledge = knowledge or SoftwareIncKnowledgeProvider()
        self._snapshot_loader = snapshot_loader

    async def load(self) -> SoftwareIncGuidanceContext:
        discovery = self._discovery.inspect()
        bridge_report: SoftwareIncBridgeReport | None
        try:
            bridge_report = self._bridge_installer.diagnose()
        except Exception:
            bridge_report = None
        snapshot: GameSnapshot | None = None
        state: SoftwareIncStateView | None = None
        error: str | None = None
        if discovery.running:
            try:
                snapshot = await self._snapshot_loader()
                state = project_state(snapshot)
            except Exception as caught:
                error = str(caught) or type(caught).__name__
        else:
            error = "Software Inc. is not running"
        capabilities = guided_capability_view(
            discovery,
            snapshot=snapshot,
            bridge_report=bridge_report,
            knowledge_topics=self.knowledge.topics(),
        )
        return SoftwareIncGuidanceContext(
            discovery=discovery,
            bridge_report=bridge_report,
            snapshot=snapshot,
            state=state,
            snapshot_error=error,
            capabilities=capabilities,
        )


__all__ = [
    "SoftwareIncGuidanceContext",
    "SoftwareIncGuidanceContextProvider",
    "SnapshotLoader",
    "collect_snapshot",
]
