# ========== STAGE 1: build PrusaSlicer 2.9.3 (CLI only) ==========
FROM debian:bookworm AS ps_build

ARG PS_VERSION=version_2.9.3
WORKDIR /src

# Toolchain & build deps (cmake, compiler, automake 1.16, ecc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential cmake ninja-build pkg-config \
    automake autoconf libtool m4 \
    perl python3 \
    curl ca-certificates \
    zlib1g-dev \
 && rm -rf /var/lib/apt/lists/*

# Sorgenti PrusaSlicer
RUN git clone --depth=1 --branch ${PS_VERSION} https://github.com/prusa3d/PrusaSlicer.git

# (Opzionale ma consigliato) build dei deps "bundled" per static link
# Nota: sulle ultime versioni c'è stata una richiesta di automake=1.16 nei deps; su Bookworm è 1.16.*
# Riferimenti: issue Automake 1.16 nei deps :contentReference[oaicite:0]{index=0}
WORKDIR /src/PrusaSlicer/deps
RUN mkdir build && cd build && \
    cmake .. -DDEP_WX_GTK3=ON && \
    make -j"$(nproc)"

# Build di PrusaSlicer **senza GUI** (solo CLI), statico
WORKDIR /src/PrusaSlicer
RUN mkdir build && cd build && \
    cmake .. -DSLIC3R_STATIC=ON -DSLIC3R_GUI=OFF -DCMAKE_BUILD_TYPE=Release && \
    make -j"$(nproc)"

# Estrai il binario e normalizza il nome a "prusaslicer"
RUN set -eux; \
    f="$(find /src/PrusaSlicer/build -type f -perm -111 \( -name 'PrusaSlicer*' -o -name 'prusa-slicer*' \) | head -n1)"; \
    test -n "$f"; \
    install -Dm755 "$f" /out/prusaslicer

# ========== STAGE 2: runtime dell'API ==========
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /api

# Runtime minimi per la tua API + cura-engine (se ti serve ancora)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    libglu1-mesa libgtk-3-0 libxrender1 libxi6 libxext6 libx11-6 libxcb1 libxfixes3 \
    cura-engine \
 && rm -rf /var/lib/apt/lists/*

# --- qui arriva il PrusaSlicer CLI compilato ---
COPY --from=ps_build /out/prusaslicer /usr/local/bin/prusaslicer

# Python deps
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Codice app
COPY api/ .

# (Facoltativo) qualche definizione Cura utile
RUN set -eux; \
    mkdir -p /api/cura_defs; \
    base="https://raw.githubusercontent.com/Ultimaker/Cura/master/resources/definitions"; \
    curl -fsSLo /api/cura_defs/fdmprinter.def.json "$base/fdmprinter.def.json" || true; \
    curl -fsSLo /api/cura_defs/creality_base.def.json "$base/creality_base.def.json" || true

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
