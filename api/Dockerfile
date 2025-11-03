FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl unzip git build-essential \
    # SLICER: curaengine dai repo Debian
    cura-engine \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements API
COPY api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# codice API + web di default (sovrascritto dal volume in compose)
COPY api/main.py /app/main.py
COPY web /app/web

EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
