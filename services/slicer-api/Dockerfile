# services/slicer-api/Dockerfile
# Non tocco il tuo codice: creo solo un venv e avvio direttamente l’API (bypass /init e openbox).

FROM xabix99/prusaslicer:latest
ENV DEBIAN_FRONTEND=noninteractive TZ=Europe/Rome

# Python + venv (PEP 668 safe)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates curl jq \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Virtualenv e dipendenze usate dalla tua API
RUN python3 -m venv /venv \
 && /venv/bin/pip install --no-cache-dir --upgrade pip wheel \
 && /venv/bin/pip install --no-cache-dir \
      fastapi uvicorn[standard] httpx requests python-multipart

# Copio ESATTAMENTE i tuoi file
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

EXPOSE 8088

# Punto chiave: BYPASSO l'entrypoint /init di linuxserver.io (che avvia openbox)
ENTRYPOINT ["/venv/bin/python","-u","/app/slice_api.py"]
