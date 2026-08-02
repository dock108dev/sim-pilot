# Software Inc. Phase 3 Verified UI Control

> This is retained Phase 3 evidence. The current staffing boundary is defined by
> [Phase 4 teams and hiring](030-software-inc-teams-and-hiring.md). Prompt 5 later hardened the
> same backend for signed multi-display coordinates and primary-display window normalization.

## Boundary

Phase 3 adds visible computer control for the exact macOS Steam build of Software Inc. It does not
add methods to the semantic bridge. At Phase 3, Game Bridge Protocol v3 remained read only with eight
observation surfaces and an empty gameplay-action catalog. A separate UI catalog initially contains
only `pause`, `resume`, and `open_manage_teams`. Hiring, team edits, projects, purchases,
construction, saving, and financial changes remain unavailable.

## Synchronized execution

Every observation uses this sequence:

```text
semantic snapshot before
-> foreground the already-running exact process
-> capture the exact current game window
-> semantic snapshot after
-> validate identities, coverage, sequence, timing, scene, modal state, and targets
```

Foreground activation resolves exactly one already-running process by Software Inc.'s bundle
identifier and activates that process directly through AppKit. It does not ask System Events to
send Apple events, does not require macOS Automation permission for Terminal, and cannot launch a
new game process. The exact PID must become frontmost before capture proceeds. Because macOS
full-screen windows may change Spaces asynchronously, the capture and input boundaries poll the
exact CoreGraphics window for at most one second; they do not send input while waiting, and a frame
that expires during the transition is rejected as stale.

Every control cycle sends zero or one gesture. A fresh synchronized observation verifies a sent
gesture. Ambiguous verification is never automatically retried.

Pause and resume resolve Software Inc. 1.8.41's visible top-center pause and normal-speed buttons
from the current frame. `force_pause` and `simulation_speed` supply the semantic postcondition, and
a fresh frame must show the corresponding paused or running gameplay scene.

Manage Teams is resolved from the current bottom-left management toolbar. A bounded search finds
the version-pinned HR group-button shape, converts the live pixel target through the observed
Retina scale, and binds it to the exact capture and window. No fixture coordinate is sent directly.
The click is allowed only while paused. A fresh frame must identify Manage Teams while the gameplay
semantic fingerprint remains unchanged. The first live opening displayed Software Inc.'s optional
Team management tutorial. Sim Pilot recognized that tutorial as a blocking modal, reported it, and
left it untouched. Re-observing the already-open Manage Teams window is a verified zero-input
success; no other action is allowed through the modal.

## Exact window capture

Software Inc.'s Unity fullscreen window is not consistently exposed as an Accessibility window.
Phase 3 enumerates CoreGraphics windows for the exact PID and accepts exactly one visible, titled,
layer-zero `Software Inc` window. A frame records a unique per-capture identifier distinct from the
pixel digest, capture sequence and timestamp, PID, CoreGraphics window number, title, logical
bounds, full content bounds, visible display regions, display identities, frontmost state, pixel
dimensions, display scale, pixel SHA-256, and platform.

macOS display coordinates are signed: a monitor left of the primary display has a negative origin.
Before capture, the current runtime checks all active CoreGraphics displays. If the game window is
partly offscreen or spans displays, it performs one Accessibility-authorized OS window move to fit
the existing window inside the primary display and verifies the same PID and CoreGraphics window.
It does not resize the game, alter a save, or send gameplay input. A window larger than the primary
display is rejected with a request to choose a fitting resolution or fullscreen mode.

Capture rejects a window change during acquisition. Input revalidates PID, window number, title,
capture and content bounds, visible regions, display identities, scale, frontmost state, capture
identity, and age. A target in an offscreen area or the gap between displays is rejected. The
Software Inc. path does not launch or restart the game or change installed bridge files.

## Input and recognition

The game-neutral macOS backend has strict payloads for left click, key plus optional modifiers,
bounded Unicode text, and bounded two-axis scrolling. Every payload names its intended effect,
scene, target, exact frame, process, window, bounds, creation time, and maximum age. Text and scroll
are offline-tested but stay outside the live Software Inc. UI catalog until a safe reversible
control is independently proven.

The version-scoped recognizer distinguishes paused gameplay, running gameplay, Manage Teams,
blocking modal, and unknown. It combines visible game-frame evidence, gameplay content, the
anchored management toolbar, button features, management-panel geometry, and semantic pause state.
Unknown, ambiguous, obscured, modal, stale, changed-window, changed-session, excessive-skew, and
unverified-effect cases fail closed.

Screenshots remain in memory by default. Owner-only JSONL traces contain hashes, identities,
targets, gestures, and verification results but no screenshot pixels:

```text
~/Library/Application Support/Sim Pilot/software-inc/ui/traces.jsonl
```

## Commands

```bash
uv run sim-pilot software-inc ui doctor
uv run sim-pilot software-inc ui observe
uv run sim-pilot software-inc ui observe --json
uv run sim-pilot software-inc ui capabilities
uv run sim-pilot software-inc ui do "pause the game"
uv run sim-pilot software-inc ui do "resume the game"
uv run sim-pilot software-inc ui do "open manage teams"
uv run sim-pilot software-inc ui do "open manage teams" --dry-run
```

`observe` and `--dry-run` send no gesture. Unsupported plain English fails before observation.

## Live evidence and validation

The live gate is Software Inc. 1.8.41, Steam build 23094975, Unity 2018.4.36f1, Mono x86_64 on
macOS. Phase 3 proved the 2.0-scale path. Prompt 5 additionally proved a three-display arrangement
at scale 1.0 where the window began at `x=-1460`, spanned two displays, and overflowed vertically;
the runtime moved it once to `x=0, y=30` on the primary display and verified the exact same window.
Windows remains unimplemented and unverified.

The bounded acceptance sequence passed on the pinned Mac without a game restart or bridge change:

- the exact CoreGraphics window was captured at 2.0 scale;
- one current-frame click resumed the paused simulation and fresh semantic plus visual state
  verified the effect;
- one current-frame click restored pause and fresh semantic plus visual state verified the effect;
- one current-frame click opened Manage Teams, which is now independently recognized together
  with its blocking first-use tutorial;
- observing and requesting the already-open window sent zero gestures;
- every runtime cycle sent at most one gesture and no ambiguous result was retried;
- the read-only proof retained an empty semantic gameplay-action catalog, identical semantic
  fingerprints (`2b35bed9...`), and identical save fingerprints
  (`3a295d8c...`) for the single save file.

Offline validation covers model rejection, unique capture identity for identical pixels,
exact-region capture, window drift, stale frames, click/key/text/scroll dispatch composition,
scene/target fixtures, modal rejection, dry run, one gesture per cycle, postcondition verification,
semantic identity drift, owner-only traces, CLI rejection, architecture direction, and the retained
read-only bridge boundary. The opt-in current-state acceptance test also passed with the tutorial
modal still visible and without sending input.
