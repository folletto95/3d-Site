# ===================== STAGE 1: build PrusaSlicer CLI =====================
FROM debian:bookworm AS ps_build
ENV LANG=C.UTF-8 LC_ALL=C.UTF-8

WORKDIR /src

# Toolchain + util per estrazione zip e build docs gmp (makeinfo)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential cmake ninja-build pkg-config \
    automake autoconf libtool m4 \
    perl python3 \
    curl ca-certificates \
    zlib1g-dev \
    unzip texinfo \
 && rm -rf /var/lib/apt/lists/*

# Sorgenti PrusaSlicer 2.9.3
ARG PS_VERSION=version_2.9.3
RUN git clone --depth=1 --branch ${PS_VERSION} https://github.com/prusa3d/PrusaSlicer.git

# Build deps (serve unzip + UTF-8; texinfo evita l'errore gmp)
WORKDIR /src/PrusaSlicer/deps
RUN mkdir build && cd build && \
    cmake .. -DDEP_WX_GTK3=ON && \
    make -j"$(nproc)"

# Build PrusaSlicer **solo CLI** (niente GUI)
WORKDIR /src/PrusaSlicer
RUN mkdir build && cd build && \
    cmake .. -DSLIC3R_STATIC=ON -DSLIC3R_GUI=OFF -DCMAKE_BUILD_TYPE=Release && \
    make -j"$(nproc)"

# Estrai il binario
RUN set -eux; f="$(find /src/PrusaSlicer/build -type f -perm -111 \
        \( -name 'PrusaSlicer*' -o -name 'prusa-slicer*' \) | head -n1)"; \
    test -n "$f"; install -Dm755 "$f" /out/prusaslicer

# ===================== STAGE 2: runtime API =====================
FROM python:3.11-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 LANG=C.UTF-8 LC_ALL=C.UTF-8
WORKDIR /api

# Runtime minimi + (se ti serve ancora) cura-engine
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    libglu1-mesa libgtk-3-0 libxrender1 libxi6 libxext6 libx11-6 libxcb1 libxfixes3 \
    cura-engine \
 && rm -rf /var/lib/apt/lists/*

# PrusaSlicer CLI dal build stage
COPY --from=ps_build /out/prusaslicer /usr/local/bin/prusaslicer

# Python deps
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codice API
COPY api/ .

# (Facoltativo) qualche def Cura
RUN set -eux; \
    mkdir -p /api/cura_defs; \
    base="https://raw.githubusercontent.com/Ultimaker/Cura/master/resources/definitions"; \
    curl -fsSLo /api/cura_defs/fdmprinter.def.json "$base/fdmprinter.def.json" || true; \
    curl -fsSLo /api/cura_defs/creality_base.def.json "$base/creality_base.def.json" || true

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
