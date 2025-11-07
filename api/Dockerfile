# syntax=docker/dockerfile:1.7-labs

############################
# Runtime con PrusaSlicer
############################
FROM debian:sid-slim

ARG DEBIAN_FRONTEND=noninteractive

# Installazione dipendenze di sistema e PrusaSlicer
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates \
      libglu1-mesa libgl1 libopengl0 \
      prusa-slicer xvfb tini \
      python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Wrapper headless compatibile con il servizio legacy e symlink "prusaslicer"
RUN printf '#!/bin/sh\nexec xvfb-run -a /usr/bin/prusa-slicer "$@"\n' > /usr/local/bin/ps-headless \
 && chmod +x /usr/local/bin/ps-headless \
 && ln -s /usr/bin/prusa-slicer /usr/local/bin/prusaslicer

WORKDIR /app

# Ambiente virtuale per FastAPI
RUN python3 -m venv /venv
ENV PATH="/venv/bin:${PATH}"

# requirements
COPY api/requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-cache-dir -r requirements.txt

# codice API
COPY api/ .

EXPOSE 8080
CMD ["uvicorn","main:app","--host","0.0.0.0","--port","8080"]
