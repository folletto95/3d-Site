# Base Debian Bookworm + Python
FROM python:3.11-slim-bookworm

# Lavoriamo sotto /api
WORKDIR /api

# Dipendenze di sistema: cura-engine 4.x, git, curl
RUN apt-get update && apt-get install -y --no-install-recommends \
    cura-engine \
    git \
    curl \
    ca-certificates \
    assimp-utils \
 && rm -rf /var/lib/apt/lists/*

# Requisiti Python
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codice API
COPY api/ .

# Definitions di Cura (versione allineata a 4.13)
ARG CURA_TAG=4.13.0
RUN set -eux; \
  mkdir -p /api/cura_defs; \
  base="https://raw.githubusercontent.com/Ultimaker/Cura/${CURA_TAG}/resources/definitions"; \
  curl -fsSL "$base/fdmprinter.def.json"  -o /api/cura_defs/fdmprinter.def.json; \
  curl -fsSL "$base/fdmextruder.def.json" -o /api/cura_defs/fdmextruder.def.json

# Porta e avvio
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]


ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \    ca-certificates curl libglu1-mesa libgtk-3-0 libxrender1 libxi6 libxext6 libx11-6 libxcb1 libxfixes3 \  && rm -rf /var/lib/apt/lists/*

ARG PRUSA_URL="https://github.com/prusa3d/PrusaSlicer/releases/download/v2.7.4/PrusaSlicer-2.7.4+linux-x64-GTK3-202405130813.AppImage"
RUN curl -L "$PRUSA_URL" -o /tmp/PrusaSlicer.AppImage && chmod +x /tmp/PrusaSlicer.AppImage \ && /tmp/PrusaSlicer.AppImage --appimage-extract -o /opt/prusaslicer \ && ln -s /opt/prusaslicer/AppRun /usr/local/bin/prusaslicer \ && rm /tmp/PrusaSlicer.AppImage
