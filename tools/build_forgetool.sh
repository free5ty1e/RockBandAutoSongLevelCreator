#!/bin/bash
# tools/build_forgetool.sh
set -e
# Ensure dotnet is in PATH (installed in /tmp/dotnet by Dockerfile)
export PATH=/tmp/dotnet:$PATH
# Build ForgeTool from the vendored source
cd "$(dirname "$0")/libforge"
dotnet build -c Release LibForge/ForgeTool/ForgeTool.csproj /p:FrameworkPathOverride=/usr/lib/mono/4.7.1-api
echo "Build complete."
