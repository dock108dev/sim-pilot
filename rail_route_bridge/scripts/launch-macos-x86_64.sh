#!/bin/sh
set -eu

game_root="${SIM_PILOT_RAIL_ROUTE_GAME_ROOT:-$HOME/Library/Application Support/Steam/steamapps/common/Rail Route}"
game_executable="$game_root/Rail Route.app/Contents/MacOS/Rail Route"
loader="$game_root/libdoorstop.dylib"
preloader="$game_root/BepInEx/core/BepInEx.Preloader.dll"
native_plugins="$game_root/Rail Route.app/Contents/PlugIns"

if [ ! -x "$game_executable" ] || [ ! -f "$loader" ] || [ ! -f "$preloader" ] || [ ! -d "$native_plugins" ]; then
  echo "The exact game and installed BepInEx files are required. Run bridge doctor and install first." >&2
  exit 2
fi
if pgrep -x "Rail Route" >/dev/null; then
  echo "Rail Route is already running; refusing a second bridge launch." >&2
  exit 2
fi
if [ "$(shasum -a 256 "$game_executable" | awk '{print $1}')" != "ef6ab0344cd13e95a8325c8a6f218b29d3735290d913a046eaf1015476d424c4" ]; then
  echo "Rail Route executable hash is unsupported." >&2
  exit 2
fi
if [ "$(shasum -a 256 "$loader" | awk '{print $1}')" != "cb4aaa97bd9a08178ac2d165b33284b744d18498d5dec5a07fc2b6f6d87d80b9" ]; then
  echo "BepInEx Doorstop hash is unsupported." >&2
  exit 2
fi

if [ "$#" -eq 0 ] || [ "$1" != "$game_executable" ]; then
  echo "Rail Route must invoke this wrapper through Steam launch options with %command%." >&2
  exit 2
fi
shift

export DOORSTOP_ENABLED=1
export DOORSTOP_TARGET_ASSEMBLY="$preloader"
export DOORSTOP_IGNORE_DISABLED_ENV=0
export DOORSTOP_MONO_DEBUG_ENABLED=0
export DYLD_LIBRARY_PATH="$game_root:$native_plugins${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"

cd "$game_root"
exec arch -x86_64 -e DYLD_INSERT_LIBRARIES="$loader" "$game_executable" "$@"
