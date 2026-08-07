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

# Locate mono's .NET Framework reference assemblies (mscorlib.dll) for
# FrameworkPathOverride. ForgeTool.csproj targets .NET Framework v4.7.1, so we
# specifically want the 4.7.1-api reference assemblies (any mono 6.x ships them).
# The path differs by OS and install method:
#   - Linux (apt mono-devel):    /usr/lib/mono/4.7.1-api
#   - macOS (old/Framework mono): /Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.7.1-api
#   - macOS (Homebrew mono, Intel & Apple Silicon): $(brew --prefix mono)/lib/mono/4.7.1-api
#     (e.g. /opt/homebrew/Cellar/mono/6.14.1/lib/mono/4.7.1-api)
# Build a candidate list (4.7.1-api first) from brew (if present) plus the standard
# Linux/Framework paths, then pick the first mscorlib.dll that actually exists.
find_framework_path() {
  local candidates=()

  if command -v brew >/dev/null 2>&1; then
    local bp
    bp="$(brew --prefix mono 2>/dev/null)"
    if [ -n "$bp" ]; then
      candidates+=("$bp/lib/mono/4.7.1-api" "$bp/lib/mono/4.8-api" "$bp/lib/mono/4.5-api")
    fi
  fi

  candidates+=(
    "/usr/lib/mono/4.7.1-api" \
    "/usr/lib/mono/4.8-api" \
    "/usr/lib/mono/4.5-api" \
    "/Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.7.1-api" \
    "/Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.8-api" \
    "/Library/Frameworks/Mono.framework/Versions/Current/lib/mono/4.5-api"
  )

  local c
  for c in "${candidates[@]}"; do
    if [ -f "$c/mscorlib.dll" ]; then
      echo "$c"
      return 0
    fi
  done

  # Fallback: search common Homebrew Cellar / Framework roots for any *-api mscorlib.dll.
  local found
  found="$(find /opt/homebrew/Cellar /usr/local/Cellar /Library/Frameworks \
    -path '*/lib/mono/*-api/mscorlib.dll' 2>/dev/null | head -n1)"
  if [ -n "$found" ]; then
    echo "$(dirname "$found")"
    return 0
  fi
  return 1
}

FRAMEWORK_PATH="$(find_framework_path)" || true
if [ -z "$FRAMEWORK_PATH" ]; then
  echo "ERROR: Could not find mono's .NET Framework 4.7.1 reference assemblies (mscorlib.dll)." >&2
  echo "  ForgeTool.csproj targets .NET Framework v4.7.1, so mono must ship the 4.7.1-api reference assemblies." >&2
  echo "  Any mono 6.x (e.g. 6.14.1) includes them. Install mono and re-run:" >&2
  echo "  - macOS:  brew install mono      # installs 6.14.1" >&2
  echo "  - Linux:  sudo apt install mono-devel   # Debian 12 / Ubuntu 22.04+ ships mono 6.8+/6.12+" >&2
  echo "  Verify with: mono --version (should be >= 6.0)" >&2
  exit 1
fi
echo "Using mono reference assemblies at: $FRAMEWORK_PATH"

cd "$(dirname "$0")/libforge"
dotnet build -c Release LibForge/ForgeTool/ForgeTool.csproj /p:FrameworkPathOverride="$FRAMEWORK_PATH"
echo "Build complete."
