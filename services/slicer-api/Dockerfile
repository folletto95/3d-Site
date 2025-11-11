## `profiles/` e `web/` non saranno inclusi nel contesto e la build fallirà.
FROM xabix99/prusaslicer:latest

ENV DEBIAN_FRONTEND=noninteractive TZ=Europe/Rome

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Librerie Python
ENV VIRTUAL_ENV=/opt/venv
RUN pip3 install --no-cache-dir fastapi uvicorn[standard] python-multipart requests
RUN python3 -m venv "$VIRTUAL_ENV" && "$VIRTUAL_ENV/bin/pip" install --upgrade pip

WORKDIR /app
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

RUN "$VIRTUAL_ENV/bin/pip" install --no-cache-dir \
    fastapi "uvicorn[standard]" python-multipart httpx requests

ENTRYPOINT ["/opt/venv/bin/uvicorn"]
CMD ["slice_api:app","--host","0.0.0.0","--port","8088"]
