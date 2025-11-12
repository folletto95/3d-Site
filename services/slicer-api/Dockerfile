# services/slicer-api/Dockerfile  (minimal install fix, NO code changes)
FROM xabix99/prusaslicer:latest

ENV DEBIAN_FRONTEND=noninteractive TZ=Europe/Rome

# Python + venv (PEP 668 safe)
RUN apt-get update && apt-get install -y --no-install-recommends         python3 python3-venv python3-pip ca-certificates       && rm -rf /var/lib/apt/lists/*

# Create virtualenv and install deps
WORKDIR /app
COPY services/slicer-api/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /venv && /venv/bin/pip install --no-cache-dir --upgrade pip wheel &&         /venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt

# App and assets (unchanged)
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

EXPOSE 8088

# Run user's app with the venv Python, no alias, no code change
CMD ["/venv/bin/python","-u","/app/slice_api.py"]
