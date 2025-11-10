# Base con PrusaSlicer CLI (linuxserver.io base con s6 e KasmVNC)
FROM xabix99/prusaslicer:latest

# Python venv per evitare PEP 668
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3-full python3-venv && \
    rm -rf /var/lib/apt/lists/*

# Venv
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

# Dipendenze app
RUN pip install --no-cache-dir \
      fastapi \
      uvicorn[standard] \
      httpx \
      python-multipart \
      jinja2

WORKDIR /app

# API
COPY services/slicer-api/slice_api.py /app/slice_api.py

# UI
COPY web /app/web

# cartelle di lavoro
RUN mkdir -p /app/work /app/profiles

EXPOSE 8088

# Avvio tramite s6 -> vedi docker-compose command
