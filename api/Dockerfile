FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1

WORKDIR /api

# System deps incl. PrusaSlicer runtime and CuraEngine
RUN apt-get update &&     apt-get install -y --no-install-recommends         ca-certificates         curl         libglu1-mesa         libgtk-3-0         libxrender1         libxi6         libxext6         libx11-6         libxcb1         libxfixes3         cura-engine     && rm -rf /var/lib/apt/lists/*

# Python deps
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY api/ .

# Cura definitions (opzionale)
RUN set -eux;     mkdir -p /api/cura_defs;     base="https://raw.githubusercontent.com/Ultimaker/Cura/master/resources/definitions";     curl -fsSLo /api/cura_defs/fdmprinter.def.json "$base/fdmprinter.def.json" || true;     curl -fsSLo /api/cura_defs/creality_base.def.json "$base/creality_base.def.json" || true

# PrusaSlicer CLI (AppImage extracted, no FUSE)
ARG PRUSA_URL="https://github.com/prusa3d/PrusaSlicer/releases/download/v2.7.4/PrusaSlicer-2.7.4+linux-x64-GTK3-202405130813.AppImage"
RUN curl -L "$PRUSA_URL" -o /tmp/PrusaSlicer.AppImage && chmod +x /tmp/PrusaSlicer.AppImage &&     /tmp/PrusaSlicer.AppImage --appimage-extract -o /opt/prusaslicer &&     ln -s /opt/prusaslicer/AppRun /usr/local/bin/prusaslicer &&     rm /tmp/PrusaSlicer.AppImage

EXPOSE 8080

# Avvio API
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
