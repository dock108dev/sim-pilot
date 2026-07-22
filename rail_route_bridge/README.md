# Sim Pilot Rail Route Bridge

This directory contains the game-neutral C# protocol/server core and the version-pinned Rail Route
BepInEx plugin. The server binds IPv4 loopback, requires the owner-only token, accepts one client,
enforces strict framing/schema/sequence rules, and advertises an empty gameplay-action catalog.
Player-visible UI input is implemented in Python; the bridge supplies read-only identity,
preconditions, and postconditions.

Run the package-free offline core/golden/integration suite:

```shell
sh rail_route_bridge/scripts/test.sh
```

Build the `netstandard2.0` game plugin against the pinned loader and exact local managed assemblies:

```shell
tmpdir=$(mktemp -d)
curl -fsSL -o "$tmpdir/bepinex.zip" \
  https://github.com/BepInEx/BepInEx/releases/download/v5.4.23.5/BepInEx_macos_universal_5.4.23.5.zip
test "$(shasum -a 256 "$tmpdir/bepinex.zip" | awk '{print $1}')" = \
  01c2ae782eb016dfd6c345a18dbd2dcafffb3d9d318449d6486689f426b4a323
unzip -q "$tmpdir/bepinex.zip" -d "$tmpdir/loader"

BEPINEX_ROOT="$tmpdir/loader/BepInEx" \
RAIL_ROUTE_MANAGED_PATH="$HOME/Library/Application Support/Steam/steamapps/common/Rail Route/Rail Route.app/Contents/Resources/Data/Managed" \
  sh rail_route_bridge/scripts/build-plugin.sh
```

The build reads game assemblies as compile-time references; it does not edit or launch the game.
`loader-lock.json` records macOS and Windows assets, architectures, checksums, license, and validation
status. Windows x64 is a build design only until tested on a real Windows installation.

Do not copy files manually. Use `uv run sim-pilot rail-route bridge install`, which verifies the
game is closed and owns every file it creates. Protocol details and live status are documented in
`docs/024-game-bridge-protocol.md` and `docs/025-rail-route-semantic-bridge.md`.

After installation, the first macOS live proof must preserve the observed x86_64/Rosetta baseline.
Direct launch is not supported because Rail Route exits through its Steam restart guard. Temporarily
set this exact Rail Route Steam launch option, replacing `<REPOSITORY>` with the absolute checkout:

```shell
"<REPOSITORY>/rail_route_bridge/scripts/launch-macos-x86_64.sh" %command%
```

Then start Rail Route normally from Steam. The launcher is explicit and checksum-gated; the
installer does not edit Steam launch options. Remove the option before recovery verification or
normal unmodded launch. Always use Steam's Library Play button for bridge runs; Dock, Finder, and
Spotlight launches bypass `%command%` and are unsupported.
