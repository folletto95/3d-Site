# services/slicer-api/Dockerfile
# Base con PrusaSlicer e Python in virtualenv (no alias, PEP 668-safe)
FROM xabix99/prusaslicer:latest

ENV DEBIAN_FRONTEND=noninteractive TZ=Europe/Rome

# Python + venv
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Virtualenv per evitare PEP 668
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir --upgrade pip wheel && \
    /venv/bin/pip install --no-cache-dir fastapi uvicorn python-multipart requests

WORKDIR /app

# API e risorse
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

EXPOSE 8088

# Avvio con l'interprete del venv
CMD ["/venv/bin/python", "-u", "/app/slice_api.py"]
