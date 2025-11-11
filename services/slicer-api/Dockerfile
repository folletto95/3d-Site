# services/slicer-api/Dockerfile
# Base con PrusaSlicer già incluso (no alias). Aggiungiamo Python e l'API FastAPI.
FROM xabix99/prusaslicer:latest

ENV DEBIAN_FRONTEND=noninteractive TZ=Europe/Rome

# Dipendenze API
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Librerie Python
RUN pip3 install --no-cache-dir fastapi uvicorn[standard] python-multipart requests

WORKDIR /app

# Copiamo l'API e le cartelle necessarie
COPY services/slicer-api/slice_api.py /app/slice_api.py
COPY profiles /profiles
COPY web /app/web

# Porta dell'API
EXPOSE 8088

# Avvio dell'API
CMD ["python3","-u","/app/slice_api.py"]
