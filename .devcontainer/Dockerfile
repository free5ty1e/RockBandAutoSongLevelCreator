FROM mcr.microsoft.com/devcontainers/python:3.11

# Install system dependencies required for audio processing and ML compiling
RUN apt-get update && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    build-essential \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install heavy ML dependencies globally to speed up rebuilds
RUN pip install --upgrade pip
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
