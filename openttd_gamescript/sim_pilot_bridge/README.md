# Sim Pilot Bridge for OpenTTD 15.3

Production GameScript package for bridge protocol v1. Install this directory as
`$HOME/Documents/OpenTTD/game/SimPilotBridge`, select `SimPilotBridge` in a
new disposable game, and connect through the loopback Admin Network.

The package publishes bounded snapshots and supports only the verified
`set_company_name` action. It does not implement construction, vehicles, route
planning, state deltas, or remote multiplayer automation.
