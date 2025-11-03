FROM python:3.11-slim-bookworm

WORKDIR /api

# Evita bytecode e buffer, e soprattutto prompt interattivi di apt
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# 1) Dipendenze di sistema: git + CuraEngine
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    cura-engine \
    && rm -rf /var/lib/apt/lists/*

# 2) Dipendenze Python
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3) Pacchetti base
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# 4) Definizioni Cura: fdmprinter / fdmextruder (prese dal repo ufficiale)
ARG CURA_TAG=5.11.0
RUN set -eux; \
  mkdir -p /api/cura_defs; \
  base="https://raw.githubusercontent.com/Ultimaker/Cura/${CURA_TAG}/resources/definitions"; \
  curl -fsSL "$base/fdmprinter.def.json"  -o /api/cura_defs/fdmprinter.def.json; \
  curl -fsSL "$base/fdmextruder.def.json" -o /api/cura_defs/fdmextruder.def.json

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
