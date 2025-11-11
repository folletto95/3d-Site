# services/slicer-api/Dockerfile  (patched)
FROM xabix99/prusaslicer:latest

ENV DEBIAN_FRONTEND=noninteractive TZ=Europe/Rome

# Python + venv to avoid PEP 668
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Virtualenv for API deps
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir --upgrade pip wheel && \
    /venv/bin/pip install --no-cache-dir fastapi uvicorn python-multipart requests

WORKDIR /app
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

EXPOSE 8088
CMD ["/venv/bin/python", "-u", "/app/slice_api.py"]
