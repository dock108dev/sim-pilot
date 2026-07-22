#!/bin/sh
set -eu
if [ "${BEPINEX_ROOT:-}" = "" ]; then
  echo "BEPINEX_ROOT must identify the pinned BepInEx 5.4.23.5 installation." >&2
  exit 2
fi
if [ "${RAIL_ROUTE_MANAGED_PATH:-}" = "" ]; then
  echo "RAIL_ROUTE_MANAGED_PATH must identify Rail Route Contents/Resources/Data/Managed." >&2
  exit 2
fi
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dotnet build "$project_root/src/SimPilot.RailRoute.Bridge/SimPilot.RailRoute.Bridge.csproj" \
  --configuration Release \
  -p:BepInExRoot="$BEPINEX_ROOT" \
  -p:RailRouteManagedPath="$RAIL_ROUTE_MANAGED_PATH"
