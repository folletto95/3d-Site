FROM xabix99/prusaslicer:latest

# Dipendenze minime per venv/pip (Debian/Ubuntu base)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-venv python3-pip ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Crea un virtualenv e aggiorna pip
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv "$VIRTUAL_ENV" \
 && "$VIRTUAL_ENV/bin/pip" install --upgrade pip

# App
WORKDIR /app
COPY services/slicer-api/slice_api.py /app/slice_api.py

# Installa dipendenze nel venv (nota le virgolette su uvicorn[standard])
RUN "$VIRTUAL_ENV/bin/pip" install --no-cache-dir fastapi "uvicorn[standard]"

# Espone e lancia
EXPOSE 8080
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
CMD ["uvicorn","slice_api:app","--host","0.0.0.0","--port","8080"]
