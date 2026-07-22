# ADR-017: Pinned BepInEx Loader for Rail Route

## Status

Accepted for reversible implementation; live compatibility pending

## Context

Rail Route 2.3.24 is a Unity 2021.3.45f2 Mono game. Screen observation cannot expose named semantic
entities. A managed plugin is the smallest candidate boundary, but it must not patch game assemblies,
change Steam configuration, or make unverified architecture claims.

## Decision

Use BepInEx 5.4.23.5 (MIT), macOS universal asset SHA-256
`01c2ae782eb016dfd6c345a18dbd2dcafffb3d9d318449d6486689f426b4a323`, and a `netstandard2.0` plugin.
On Windows the design pins the x64 asset SHA-256
`82f9878551030f54657792c0740d9d51a09500eeae1fba21106b0c441e6732c4`, but Windows remains
unvalidated.

Install only allowlisted files under the resolved Steam game directory. Record every owned file and
checksum outside the game in an owner-only manifest. Refuse collisions, symlinks, unexpected builds,
running-game installation, or changed owned files. Disable by moving only the plugin to its recorded
disabled name. Uninstall only unchanged owned files and preserve unknown/generated data.

First live validation must preserve the observed x86_64/Rosetta launch. Native ARM64 is a separate
validation path even though both game and loader binaries contain ARM64 slices.

## Rejected alternatives

Assembly rewriting is destructive. Raw Doorstop would recreate lifecycle and loader safety.
MelonLoader and Unity Mod Manager lack stronger demonstrated support for this exact macOS target.
Process memory, debugger injection, and screen-derived entities are too brittle or invasive.

