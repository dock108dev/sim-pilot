"""Diagnostic composition for Software Inc. verified UI control."""

from __future__ import annotations

from sim_pilot.software_inc.discovery import SoftwareIncDiscovery

from .models import SoftwareIncUIDoctorReport
from .observer import SoftwareIncUIObserver, software_inc_ui_backend
from .platform import software_inc_window_identity


async def diagnose_ui() -> SoftwareIncUIDoctorReport:
    discovery = SoftwareIncDiscovery().inspect()
    backend = software_inc_ui_backend()
    capabilities = backend.capabilities()
    reasons: list[str] = []
    window = None
    bridge_available = False
    if discovery.process_id is None:
        reasons.append("exact Software Inc. process is not running")
    else:
        try:
            # Observation performs exact activation, window capture, and bridge synchronization.
            observed = await SoftwareIncUIObserver(backend=backend).observe()
            window = software_inc_window_identity(discovery.process_id)
            bridge_available = True
            if observed.observation.scene.value == "unknown":
                reasons.append("current Software Inc. UI scene is unknown")
        except Exception as error:
            reasons.append(str(error))
    safe = (
        not reasons
        and capabilities.exact_window_capture
        and capabilities.screen_capture
        and capabilities.accessibility_trusted
        and bridge_available
        and window is not None
    )
    return SoftwareIncUIDoctorReport(
        safe=safe,
        process_id=discovery.process_id,
        window_id=None if window is None else window.window_id,
        window_title=None if window is None else window.title,
        window_bounds=None if window is None else window.bounds,
        display_scale=None if window is None else window.display_scale,
        frontmost=None if window is None else window.frontmost,
        exact_window_capture=capabilities.exact_window_capture,
        screen_capture=capabilities.screen_capture,
        accessibility_trusted=capabilities.accessibility_trusted,
        bridge_available=bridge_available,
        game_version=discovery.product_version,
        steam_build_id=discovery.steam_build_id,
        reasons=tuple(reasons),
    )


__all__ = ["diagnose_ui"]
