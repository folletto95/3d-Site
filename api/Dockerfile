# syntax=docker/dockerfile:1.7-labs
FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Build args (opzionali)
ARG PRUSA_URL=""
ARG BAMBU_URL="https://github.com/bambulab/BambuStudio/releases/download/v01.11.01.64/BambuStudio-ubuntu-x64-v01.11.01.64.AppImage"

# Runtime deps minimi (NO toolkit GUI)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates curl jq unzip xz-utils \
        libc6 libstdc++6 libgcc-s1 libtbb2 \
        libgl1 libglu1-mesa libx11-6 libxext6 libxrender1 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

# Utente non-root
RUN useradd -m -u 1000 app && mkdir -p /data /opt/tools && chown -R app:app /data /opt/tools
WORKDIR /opt/tools

# --- CuraEngine da BambuStudio AppImage (headless) ---
RUN set -eux; \
    curl -L --fail -o bambu.AppImage "$BAMBU_URL"; \
    curl -L --fail -o jextract https://github.com/ivan-hc/jextract/raw/main/jextract; \
    chmod +x jextract; \
    ./jextract bambu.AppImage; \
    CE_PATH="$(printf '%s\n' squashfs-root/usr/bin/CuraEngine squashfs-root/opt/curaengine/CuraEngine | head -n1)"; \
    if [[ ! -x "$CE_PATH" ]]; then \
      CE_PATH="$(grep -Rsl --null -m1 -E '/CuraEngine$' squashfs-root 2>/dev/null | head -z -n1)"; \
    fi; \
    install -D "$CE_PATH" /opt/curaengine/CuraEngine; \
    mkdir -p /opt/curaengine/resources; \
    if compgen -G "squashfs-root/usr/share/cura/resources/*" > /dev/null; then \
      cp -r squashfs-root/usr/share/cura/resources/* /opt/curaengine/resources/ || true; \
    fi; \
    rm -rf squashfs-root bambu.AppImage jextract

ENV CURAENGINE_BIN=/opt/curaengine/CuraEngine
ENV CURAENGINE_RES=/opt/curaengine/resources

# --- PrusaSlicer CLI (da AppImage se PRUSA_URL è valorizzato) ---
RUN set -eux; \
    if [[ -n "$PRUSA_URL" ]]; then \
      curl -L --fail -o prusa.AppImage "$PRUSA_URL"; \
      curl -L --fail -o jextract https://github.com/ivan-hc/jextract/raw/main/jextract; \
      chmod +x jextract; \
      ./jextract prusa.AppImage; \
      PS_BIN="$(grep -Rsl --null -m1 -E '/prusa-?slicer$' squashfs-root/usr/bin || true)"; \
      if [[ -z "$PS_BIN" ]]; then PS_BIN="squashfs-root/usr/bin/prusa-slicer"; fi; \
      install -D "$PS_BIN" /opt/prusaslicer/prusaslicer; \
      rm -rf squashfs-root prusa.AppImage jextract; \
    else \
      echo "PRUSA_URL non impostata; atteso /opt/prusaslicer/prusaslicer fornito da build stage o COPY."; \
    fi

# CLI in PATH
RUN ln -sf /opt/prusaslicer/prusaslicer /usr/local/bin/prusaslicer && \
    ln -sf /opt/curaengine/CuraEngine /usr/local/bin/CuraEngine

# Env app
ENV PYTHONUNBUFFERED=1 UVICORN_WORKERS=1 \
    SPOOLMAN_URL=http://127.0.0.1:7912 \
    HOURLY_RATE=1 CURRENCY=EUR MAX_UPLOAD_MB=100

# --- App Python ---
WORKDIR /app
COPY api/requirements.txt /app/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r /app/requirements.txt
COPY api /app
RUN chown -R app:app /app
USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=5 CMD curl -fsS http://127.0.0.1:8080/health || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
