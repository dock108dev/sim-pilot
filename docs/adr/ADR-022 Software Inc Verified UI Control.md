# ADR-022: Software Inc. Verified UI Control

## Status

Accepted and live-proven for Phase 3; evidence is version- and machine-scoped.

## Context

Software Inc.'s public API supplies proven read-only semantics but no reviewed gameplay-mutation
surface. Ordinary player-visible UI interaction is required for unsupported controls. Unity's
fullscreen game window remains visible to CoreGraphics even when absent from the Accessibility
window list.

## Decision

- Game Bridge Protocol v3 remains read only with an empty gameplay-action catalog.
- A separate Software Inc. UI catalog grants only individually proven visible actions.
- The existing exact process is foregrounded through direct AppKit activation of exactly one
  matching bundle; UI control neither sends Apple events through System Events nor launches or
  restarts the game. The resolved PID and exact CoreGraphics window must become frontmost. A
  full-screen Space transition may settle for at most one second, after which control fails closed;
  a target that becomes stale during that wait is rejected.
- CoreGraphics enumeration binds capture to one visible, titled, layer-zero window for the exact
  PID. Accessibility window discovery is not fullscreen-capture authority.
- Capture identity is unique per event and separate from pixel SHA-256.
- Current-frame targets bind to process, window, bounds, scale, scene, projection, capture, and
  expiration.
- A cycle sends at most one gesture. Verification always uses a new semantic/screenshot bundle.
- Input that may have been sent is never automatically retried.
- Screenshots are ephemeral by default; owner-only traces store metadata and hashes.
- Game-specific recognition stays under `sim_pilot.software_inc.ui`; native input stays under
  `sim_pilot.computer_control`.
- A recognized first-use tutorial is a blocking modal. Sim Pilot does not dismiss it. An already
  visible Manage Teams window may be verified with zero input, but every other action remains
  blocked until the player resolves the tutorial.

## Consequences

The first bounded actions are pause, resume, and opening Manage Teams. Unknown scenes, visual
layout changes, modals, and window drift block control. Text and scrolling have no Software Inc.
live authority without a separate safe proof. Windows remains unverified. Future gameplay actions
require their own semantic, policy, approval, reconciliation, and live-proof decisions.

The macOS acceptance sequence live-verified one-click resume, one-click pause, and one-click Manage
Teams navigation. A fresh observation recognized the resulting window and tutorial modal; a
subsequent zero-input verification and the read-only bridge proof left semantic and save-file
fingerprints unchanged. No restart or bridge replacement was needed.
