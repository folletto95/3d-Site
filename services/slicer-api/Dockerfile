FROM xabix99/prusaslicer:latest

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV" && "$VIRTUAL_ENV/bin/pip" install --upgrade pip

WORKDIR /app
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

RUN "$VIRTUAL_ENV/bin/pip" install --no-cache-dir \
    fastapi "uvicorn[standard]" python-multipart httpx

# ascolta direttamente su 8088
ENTRYPOINT ["/opt/venv/bin/uvicorn"]
CMD ["slice_api:app","--host","0.0.0.0","--port","8088"]
