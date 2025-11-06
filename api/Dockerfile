# syntax=docker/dockerfile:1.7-labs

############################
# Fase "slicer": riusa l'immagine ps-headless
############################
FROM ps-headless:local AS slicer

############################
# Runtime API
############################
FROM python:3.11-slim-bookworm

ARG DEBIAN_FRONTEND=noninteractive
# dipendenze minime runtime + ciò che serve a prusaslicer
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      libstdc++6 libgcc-s1 libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

# porta dentro prusaslicer e le sue libs private dall'immagine ps-headless
COPY --from=slicer /usr/local/bin/prusaslicer /usr/local/bin/prusaslicer
COPY --from=slicer /opt/ps/usr-local /opt/ps/usr-local
ENV LD_LIBRARY_PATH=/opt/ps/usr-local/lib:$LD_LIBRARY_PATH

WORKDIR /app
# requirements
COPY api/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# codice API
COPY api/ .

EXPOSE 8080
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8080"]
