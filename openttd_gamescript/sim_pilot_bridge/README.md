# Sim Pilot Bridge for OpenTTD 15.3

Production GameScript package for bridge protocol v2. Install this directory as
`$HOME/Documents/OpenTTD/game/SimPilotBridge`, select `SimPilotBridge` in a
new disposable game, and connect through the loopback Admin Network.

The package publishes bounded summary snapshots and paginated world collections, and supports only
the verified `set_company_name` action. It does not implement construction, vehicle mutations,
state deltas, or remote multiplayer automation.
