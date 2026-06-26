#!/usr/bin/env bash
# Build the oracle and run its headless leak proof. Exit 0 == leaks as designed.
# Locates a local .NET 8 SDK (~/.dotnet or on PATH); install via https://dot.net/v1/dotnet-install.sh
# if absent. No display required — safe in CI.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
proj="$here/../LeakyOracle"

if command -v dotnet >/dev/null 2>&1; then
  DOTNET=dotnet
elif [ -x "$HOME/.dotnet/dotnet" ]; then
  export DOTNET_ROOT="$HOME/.dotnet"
  export PATH="$HOME/.dotnet:$PATH"
  DOTNET="$HOME/.dotnet/dotnet"
else
  echo "no .NET SDK found (need 8.0). Install: https://dot.net/v1/dotnet-install.sh --channel 8.0" >&2
  exit 127
fi

export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_NOLOGO=1

"$DOTNET" build -c Release -v quiet "$proj/LeakyOracle.csproj"
exec "$DOTNET" "$proj/bin/Release/net8.0/LeakyOracle.dll" --leak-scenario
