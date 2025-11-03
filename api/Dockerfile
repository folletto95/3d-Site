FROM python:3.11-slim

WORKDIR /app

# 1) Dipendenze di sistema: git + cura-engine
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        cura-engine \
    && rm -rf /var/lib/apt/lists/*

# 2) Dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3) Codice dell'app (compresi main.py e cura_defs con i file Bambu)
COPY . .

# 4) Scarica le definizioni base di Cura e copiale in /app/cura_defs
#    - fdmprinter.def.json  → definizione generica stampante FDM
#    - fdmextruder.def.json → definizione generica estrusore FDM
RUN mkdir -p /app/cura_defs && \
    git clone --depth 1 https://github.com/Ultimaker/Cura.git /tmp/cura_src && \
    cp /tmp/cura_src/resources/definitions/fdmprinter.def.json /app/cura_defs/ && \
    cp /tmp/cura_src/resources/extruders/fdmextruder.def.json /app/cura_defs/ && \
    rm -rf /tmp/cura_src

# (Opzionale ma carino)
EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
