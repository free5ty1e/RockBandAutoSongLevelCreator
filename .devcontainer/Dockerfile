FROM mcr.microsoft.com/devcontainers/python:3.11

# Install system dependencies required for audio processing and ML compiling
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    pkg-config \
    libopus-dev \
    build-essential \
    git \
    wget \
    unzip \
    curl \
    mono-devel \
    patchelf \
    wine64 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Fetch and install Mackiloha tools for your export toolchain
# RUN wget https://github.com/PikminGuts92/Mackiloha/releases/download/v1.3.2/Mackiloha_v1.3.2-linux-x64.zip -O /tmp/mackiloha.zip \
#     && unzip /tmp/mackiloha.zip -d /tmp/mackiloha \
#     && mv /tmp/mackiloha/arkhelper /usr/local/bin/ \
#     && chmod +x /usr/local/bin/arkhelper \
#     && rm -rf /tmp/mackiloha*

    
# Upgrade pip and install heavy ML dependencies globally to speed up rebuilds
RUN pip install --upgrade pip
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# ---- Clone Hero headless playtest harness (box64 + Clone Hero + ALSA-seq shim) ----
# Idempotent installer (tools/setup_clone_hero_headless.sh) baked into the image so
# devcontainer rebuilds reuse the cached install instead of re-downloading (~1.2 GB)
# and rebuilding box64 every time. post-install.sh runs the same script again as a
# no-op safety net. See autorb/testing and tools/clone_hero_headless.sh.
RUN bash tools/setup_clone_hero_headless.sh
