FROM xabix99/prusaslicer:latest

# Python per l'API
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-venv python3-pip ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY slice_api.py /app/slice_api.py

RUN python3 -m pip install --no-cache-dir fastapi uvicorn[standard]

# Montiamo volumi da compose su /in /out /profiles /logs
EXPOSE 8080
CMD ["uvicorn", "slice_api:app", "--host", "0.0.0.0", "--port", "8080"]
