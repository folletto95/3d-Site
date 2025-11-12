FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Europe/Rome

# System deps for PrusaSlicer AppImage + Python runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libasound2 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcairo2 \
        libdbus-1-3 \
        libegl1 \
        libfontconfig1 \
        libgdk-pixbuf-2.0-0 \
        libgl1 \
        libglu1-mesa \
        libgtk-3-0 \
        libgusb2 \
        libice6 \
        libfuse2 \
        libopengl0 \
        libpulse0 \
        libsm6 \
        libwayland-client0 \
        libwayland-cursor0 \
        libx11-6 \
        libxcomposite1 \
        libxcursor1 \
        libxdamage1 \
        libxext6 \
        libxfixes3 \
        libxi6 \
        libxinerama1 \
        libxkbcommon0 \
        libxrandr2 \
        libxrender1 \
        libxtst6 \
        libpangocairo-1.0-0 \
        libpango-1.0-0 \
        python3 \
        python3-venv \
        python3-pip \
        unzip \
    && rm -rf /var/lib/apt/lists/*

# Install PrusaSlicer AppImage (GTK3 build)
ARG PRUSASLICER_VERSION=2.7.4
ARG PRUSASLICER_BUILD=202404050928
ARG PRUSASLICER_FLAVOUR=linux-x64-GTK3
ARG PRUSASLICER_URL=https://github.com/prusa3d/PrusaSlicer/releases/download/version_${PRUSASLICER_VERSION}/PrusaSlicer-${PRUSASLICER_VERSION}%2B${PRUSASLICER_FLAVOUR}-${PRUSASLICER_BUILD}.AppImage

# Optional local cache: drop a PrusaSlicer *.AppImage into services/slicer-api/vendor
# to reuse it instead of downloading the installer every time the image is rebuilt.
COPY services/slicer-api/vendor/ /tmp/prusaslicer-cache/

RUN set -eux; \
    INSTALLER_PATH="$(find /tmp/prusaslicer-cache -maxdepth 1 -type f -name '*.AppImage' -print -quit || true)"; \
    if [ -n "$INSTALLER_PATH" ]; then \
        echo "Using cached PrusaSlicer installer: $(basename "$INSTALLER_PATH")"; \
        cp "$INSTALLER_PATH" /tmp/PrusaSlicer.AppImage; \
    else \
        echo "Downloading PrusaSlicer installer from $PRUSASLICER_URL"; \
        curl -fsSL "$PRUSASLICER_URL" -o /tmp/PrusaSlicer.AppImage; \
    fi; \
    chmod +x /tmp/PrusaSlicer.AppImage; \
    EXTRACT_DIR="$(mktemp -d /tmp/prusaslicer-extract.XXXXXX)"; \
    (cd "$EXTRACT_DIR" && /tmp/PrusaSlicer.AppImage --appimage-extract); \
    rm -rf /opt/prusaslicer; \
    mv "$EXTRACT_DIR/squashfs-root" /opt/prusaslicer; \
    rm /tmp/PrusaSlicer.AppImage; \
    rm -rf /tmp/prusaslicer-cache "$EXTRACT_DIR"

# Provide a stable CLI wrapper
RUN ln -s /opt/prusaslicer/AppRun /usr/local/bin/prusaslicer-appimage \
    && ln -sf /opt/prusaslicer/usr/bin/prusa-slicer-console /usr/local/bin/prusa-slicer-console \
    && printf '#!/bin/sh\nexec /opt/prusaslicer/usr/bin/prusa-slicer-console "$@"\n' > /usr/local/bin/prusaslicer-cli \
    && chmod +x /usr/local/bin/prusaslicer-cli \
    && ln -s /usr/local/bin/prusaslicer-cli /usr/local/bin/PrusaSlicer

ENV PRUSASLICER_BIN=/usr/local/bin/prusaslicer-cli

# Python virtualenv with API dependencies
RUN python3 -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip wheel \
    && /venv/bin/pip install --no-cache-dir fastapi uvicorn python-multipart requests httpx

WORKDIR /app
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

EXPOSE 8088
CMD ["/venv/bin/python","-m","uvicorn","slice_api:app","--host","0.0.0.0","--port","8088","--proxy-headers"]
