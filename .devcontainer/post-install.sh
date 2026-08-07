#!/bin/bash
set -e

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y patchelf

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Patching ctranslate2 to fix execstack crash..."
CT2_LIB=$(find ~/.local/lib /usr/local/lib /opt /usr/lib -type f -name "libctranslate2-*.so*" 2>/dev/null | head -n 1)

if [ -n "$CT2_LIB" ]; then
    patchelf --clear-execstack "$CT2_LIB"
    echo "Successfully patched: $CT2_LIB"
else
    echo "Warning: libctranslate2-*.so* not found. Did the pip install fail?"
fi

echo "Installing .NET SDK for ForgeTool build..."
curl -sSL https://dot.net/v1/dotnet-install.sh | bash /dev/stdin --channel 8.0 --install-dir /tmp/dotnet
export PATH=/tmp/dotnet:$PATH

echo "Building ForgeTool..."
bash tools/build_forgetool.sh
