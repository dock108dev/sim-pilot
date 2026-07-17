# OpenTTD GameScript discovery probes

This directory is Task 7A evidence, not the production bridge. The bundled
GameScript targets OpenTTD 15.3 / GameScript API 15 and communicates through
the official Admin Network GameScript packets.

Install it only in the disposable dedicated-server profile:

```sh
mkdir -p "$HOME/Documents/OpenTTD/game/SimPilotGSDiscovery"
cp discovery/openttd_gamescript/game_script/*.nut \
  "$HOME/Documents/OpenTTD/game/SimPilotGSDiscovery/"
```

Select `SimPilotGSDiscovery` under `[game_scripts]` in the disposable
profile's `openttd.cfg`, then start a new disposable game. Do not point these
probes at an ordinary save or a public server.

Read-only loopback probe:

```sh
source "$HOME/Documents/OpenTTD/sim-pilot.env"
SIM_PILOT_LIVE_OPENTTD_GS=1 \
  uv run python -m discovery.openttd_gamescript.probes.admin_bridge_probe
```

The reversible company-name probe has a second opt-in:

```sh
SIM_PILOT_LIVE_OPENTTD_GS=1 \
SIM_PILOT_OPENTTD_GS_DISCOVERY_WRITES=1 \
  uv run python -m discovery.openttd_gamescript.probes.admin_bridge_probe --write
```

The probe prints the selected server and company, redacts the Admin password,
and includes before/after company state. The GameScript restores the original
company name before acknowledging completion.
