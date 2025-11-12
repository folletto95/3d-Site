# services/slicer-api/Dockerfile
# NON tocca il tuo codice: crea solo un venv e installa le dipendenze che mancano.

FROM xabix99/prusaslicer:latest
ENV DEBIAN_FRONTEND=noninteractive TZ=Europe/Rome

# Python + venv (PEP 668 safe) + tool utili per debug
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates curl jq \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Virtualenv e dipendenze Python richieste dalla tua API
# (httpx mancante nei tuoi log; fastapi/uvicorn richiesti dall'app)
RUN python3 -m venv /venv \
 && /venv/bin/pip install --no-cache-dir --upgrade pip wheel \
 && /venv/bin/pip install --no-cache-dir \
      fastapi uvicorn[standard] httpx requests python-multipart

# Copio il TUO codice e le risorse così come sono
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

EXPOSE 8088

# Avvio ESATTAMENTE il tuo script (niente alias, niente uvicorn forzato)
CMD ["/venv/bin/python","-u","/app/slice_api.py"]
