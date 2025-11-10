from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os, tempfile, subprocess, json
import httpx

app = FastAPI(title="slicer-api", version="0.3.0")

# === UI statica su /ui ===
app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")

@app.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
def healthz():
    return "ok"

# === Spoolman bridge: /api/spools ===
# Env:
#   SPOOLMAN_URL   es. http://spoolman:8000  oppure http://IP:PORT
#   SPOOLMAN_TOKEN (opzionale) Bearer token
@app.get("/api/spools")
async def get_spools():
    base = os.getenv("SPOOLMAN_URL", "").rstrip("/")
    if not base:
        raise HTTPException(503, "SPOOLMAN_URL non impostato")

    headers = {}
    token = os.getenv("SPOOLMAN_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Proviamo più endpoint noti, prendendo il 1° che risponde 200
    candidates = [
        "/api/v1/spool/?page_size=1000",
        "/api/v1/spools?page_size=1000",
        "/api/spool/?page_size=1000",
    ]

    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        data = None
        last_err = None
        for path in candidates:
            try:
                r = await client.get(f"{base}{path}")
                if r.status_code == 200:
                    data = r.json()
                    break
            except Exception as e:
                last_err = str(e)
        if data is None:
            raise HTTPException(502, f"Impossibile leggere Spoolman ({last_err or 'no 200'})")

    # Normalizza: lista spools
    if isinstance(data, dict):
        spools = data.get("results") or data.get("spools") or []
    elif isinstance(data, list):
        spools = data
    else:
        spools = []

    out = []
    for s in spools:
        # estrazioni flessibili per adattarsi a diverse versioni API
        fil = s.get("filament", {}) if isinstance(s, dict) else {}
        mat = (
            (fil.get("material") or {}).get("name")
            if isinstance(fil.get("material"), dict) else fil.get("material")
        ) or s.get("material") or "N/D"

        color_name = (
            fil.get("color_name") or fil.get("colour_name")
            or (s.get("color") or {}).get("name")
            or s.get("color_name") or s.get("name") or "—"
        )

        color_hex = (
            fil.get("color_hex") or fil.get("colour_hex")
            or (s.get("color") or {}).get("hex")
            or s.get("color_hex") or "#777777"
        )

        price_per_kg = (
            s.get("price_per_kg") or s.get("cost_per_kg")
            or fil.get("price_per_kg") or fil.get("cost_per_kg")
        )

        out.append({
            "material": str(mat),
            "color_name": str(color_name),
            "color_hex": str(color_hex),
            "price_per_kg": float(price_per_kg) if isinstance(price_per_kg, (int, float, str)) and str(price_per_kg).replace('.', '', 1).isdigit() else None,
        })

    # ordina per materiale/colore
    out.sort(key=lambda x: (x["material"].lower(), x["color_name"].lower()))
    return JSONResponse(out)

# === Esempio slicing (resta invariato) ===
@app.post("/api/slice", response_class=PlainTextResponse)
async def slice_model(
    model: UploadFile = File(..., description="STL/3MF da slicare"),
    preset_print: str | None = Form(None),
    preset_filament: str | None = Form(None),
    preset_printer: str | None = Form(None),
):
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, model.filename)
        with open(in_path, "wb") as f:
            f.write(await model.read())

        out_path = os.path.join(td, "out.gcode")

        args = [
            "PrusaSlicer",
            "--export-gcode",
            "--load", "/profiles/print.ini",
            "--load", "/profiles/filament.ini",
            "--load", "/profiles/printer.ini",
            in_path,
            "-o", out_path,
        ]
        if preset_print:    args += ["--load", preset_print]
        if preset_filament: args += ["--load", preset_filament]
        if preset_printer:  args += ["--load", preset_printer]

        try:
            subprocess.run(args, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            tail = (e.stderr or e.stdout or "")[-4000:]
            raise HTTPException(status_code=500, detail=f"Slicer failed:\n{tail}")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as g:
            return g.read()
