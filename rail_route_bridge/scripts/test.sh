#!/bin/sh
set -eu
project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dotnet run --project "$project_root/tests/SimPilot.GameBridge.Core.Tests/SimPilot.GameBridge.Core.Tests.csproj" --configuration Release
