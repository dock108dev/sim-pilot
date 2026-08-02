# Software Inc. official mod probe

Prompt 1 uses Software Inc.'s documented `ModMeta` and `ModBehaviour` lifecycle to prove that an
official source mod can load. The probe logs only activation, game-ready, and deactivation
markers with the current managed thread ID. It exposes no transport or gameplay action, requests no
`GiveMeFreedom` access and declares no save serialization.

`bridge/` is the compiled read-only semantic bridge. It uses `GiveMeFreedom` only
for an owner-only authentication-token read and an authenticated loopback listener. Installation
requires explicit CLI approval. It declares no save serialization, contains no action messages, and
hands every Software Inc. API read to Unity's main thread. Later observation revisions add
applicants, visible UI geometry, rooms, placed furniture, schedules, roles, and server groups while
the protocol gameplay-action catalog remains empty.

Adapter `software-inc-readonly-v10` preserves the v9 contract behavior and adds the current
software-type/feature catalog, released products, and the visible New software design state and
controls. The bridge only reads public game state and current Unity UI geometry on Unity's main
thread. It never invokes furniture, contract, work-item, review, Education, design-document, or UI
callbacks and continues to advertise an empty gameplay-action catalog.

Install it only through `sim-pilot software-inc probe install`, which records exact ownership and
refuses to modify files while Software Inc. is running.

Validate it against one exact installation with:

```shell
dotnet build probe/SimPilotDiscoveryProbe.csproj \
  -p:SoftwareIncManagedPath="/absolute/path/to/Software Inc.app/Contents/Resources/Data/Managed"
```

Build the exact compiled bridge with the same managed path:

```shell
dotnet build bridge/SimPilotSoftwareIncBridge.csproj \
  -p:SoftwareIncManagedPath="/absolute/path/to/Software Inc.app/Contents/Resources/Data/Managed" \
  --configuration Release
```

Install, verify, disable, or uninstall it only through `sim-pilot software-inc bridge`; close the
game before changing bridge bytes.
