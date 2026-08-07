#!/bin/bash
# tools/build_forgetool.sh
set -e
# Ensure dotnet is in PATH (installed in /tmp/dotnet by the Dockerfile).
export PATH=/tmp/dotnet:$PATH

# Build ForgeTool from the vendored source. It needs the .NET SDK 8 toolchain
# (dotnet) plus mono-devel. Fail fast with clear install guidance rather than
# letting `dotnet: command not found` confuse the user.
if ! command -v dotnet >/dev/null 2>&1; then
  echo "ERROR: 'dotnet' not found. Building ForgeTool requires the .NET SDK 8." >&2
  echo "  - devcontainer: already installed in /tmp/dotnet (no action needed)." >&2
  echo "  - macOS:         brew install --cask dotnet-sdk@8" >&2
  echo "  - Linux:         see https://dotnet.microsoft.com/en-us/download/dotnet/8.0" >&2
  echo "    (e.g. Debian/Ubuntu: wget https://dot.net/v1/dotnet-install.sh -O /tmp/dotnet-install.sh" >&2
  echo "         && chmod +x /tmp/dotnet-install.sh" >&2
  echo "         && /tmp/dotnet-install.sh --channel 8.0 --install-dir /tmp/dotnet)" >&2
  echo "After installing, re-run this script." >&2
  exit 1
fi

if ! command -v mono >/dev/null 2>&1; then
  echo "ERROR: 'mono' not found. Building/running ForgeTool also requires mono-devel." >&2
  echo "  - macOS:  brew install mono" >&2
  echo "  - Linux:  sudo apt install mono-devel   (or: sudo dnf install mono-devel / sudo pacman -S mono)" >&2
  exit 1
fi

# Locate mono's .NET Framework 4.x reference assemblies (mscorlib.dll) for
# FrameworkPathOverride. The path differs by OS:
#   - Linux (apt mono-devel): /usr/lib/mono/4.7.1-api
#   - macOS (Homebrew mono):  /Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.7.1-api
# Pick the first candidate that actually exists so the same script works on both.
FRAMEWORK_PATH=""
for candidate in \
  "/usr/lib/mono/4.7.1-api" \
  "/usr/lib/mono/4.8-api" \
  "/usr/lib/mono/4.5-api" \
  "/Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.7.1-api" \
  "/Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.8-api" \
  "/Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.5-api"; do
  if [ -f "$candidate/mscorlib.dll" ]; then
    FRAMEWORK_PATH="$candidate"
    break
  fi
done

if [ -z "$FRAMEWORK_PATH" ]; then
  echo "ERROR: Could not find mono's .NET Framework reference assemblies (mscorlib.dll)." >&2
  echo "  Building ForgeTool needs mono's 4.x reference assemblies." >&2
  echo "  - macOS:  brew install mono   (installs to /Library/Frameworks/Mono.framework)" >&2
  echo "  - Linux:  sudo apt install mono-devel" >&2
  exit 1
fi
echo "Using mono reference assemblies at: $FRAMEWORK_PATH"

cd "$(dirname "$0")/libforge"
dotnet build -c Release LibForge/ForgeTool/ForgeTool.csproj /p:FrameworkPathOverride="$FRAMEWORK_PATH"
echo "Build complete."
