"""Exact-process foreground choreography for Software Inc. bridge requests."""

from __future__ import annotations

import subprocess

from sim_pilot.software_inc.errors import SoftwareIncForegroundError

_BUNDLE_IDENTIFIER = "unity.Coredumping.Software Inc"
_FOREGROUND_SCRIPT = f"""
ObjC.import("AppKit");
const applications = $.NSRunningApplication.runningApplicationsWithBundleIdentifier(
  "{_BUNDLE_IDENTIFIER}"
);
if (Number(applications.count) !== 1) {{
  throw new Error("exact Software Inc. process is not running or is ambiguous");
}}
const application = applications.objectAtIndex(0);
const processID = Number(application.processIdentifier);
if (!application.activateWithOptions($.NSApplicationActivateIgnoringOtherApps)) {{
  throw new Error("AppKit rejected activation of the exact Software Inc. process");
}}
$.NSThread.sleepForTimeInterval(0.15);
const frontmost = Number($.NSWorkspace.sharedWorkspace.frontmostApplication.processIdentifier);
if (frontmost !== processID) {{
  throw new Error("exact Software Inc. process did not become frontmost");
}}
String(processID);
""".strip()


def foreground_running_software_inc() -> None:
    """Foreground exactly one existing game process without launching an application."""
    completed = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", _FOREGROUND_SCRIPT],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else "failed"
        raise SoftwareIncForegroundError(f"could not foreground running Software Inc.: {detail}")


__all__ = ["foreground_running_software_inc"]
