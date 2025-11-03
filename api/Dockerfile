FROM python:3.11-slim

WORKDIR /app

# Evita bytecode e buffer, e soprattutto prompt interattivi di apt
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DEBIAN_FRONTEND=noninteractive

# 1) Dipendenze di sistema: git + CuraEngine
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    cura-engine \
    && rm -rf /var/lib/apt/lists/*

# 2) Dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3) Codice dell'app (main.py, cura_defs con i json Bambu, ecc.)
COPY . .

# 4) Aggiungi le definizioni base di Cura (fdmprinter / fdmextruder)
RUN mkdir -p /app/cura_defs && \
    git clone --depth 1 https://github.com/Ultimaker/Cura.git /tmp/cura_src && \
    cp /tmp/cura_src/resources/definitions/fdmprinter.def.json /app/cura_defs/ && \
    cp /tmp/cura_src/resources/extruders/fdmextruder.def.json /app/cura_defs/ && \
    rm -rf /tmp/cura_src

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
