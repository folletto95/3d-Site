from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os, tempfile, subprocess
import httpx

app = FastAPI(title="slicer-api", version="0.4.0")

# === UI statica su /ui ===
app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")

@app.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
def healthz():
    return "ok"

# === Spoolman bridge: /api/spools ===
# Env obbligatoria: SPOOLMAN_URL (es. http://192.168.10.164:7912)
# Env opzionale:    SPOOLMAN_TOKEN (Bearer), SPOOLMAN_SPOOLS_PATH (override endpoint)
@app.get("/api/spools")
async def get_spools():
    base = os.getenv("SPOOLMAN_URL", "").rstrip("/")
    if not base:
        raise HTTPException(503, "SPOOLMAN_URL non impostato")

    headers = {}
    token = os.getenv("SPOOLMAN_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # ordine di tentativi; puoi forzare con SPOOLMAN_SPOOLS_PATH
    override_path = os.getenv("SPOOLMAN_SPOOLS_PATH")
    candidates = [override_path] if override_path else [
        "/api/v1/spool/?page_size=1000",
        "/api/v1/spools?page_size=1000",
        "/api/spool/?page_size=1000",
        "/api/spools?page_size=1000",
    ]

    attempted = []
    data = None
    last_err = None

    async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
        for path in candidates:
            if not path:
                continue
            url = f"{base}{path}"
            attempted.append(url)
            try:
                r = await client.get(url)
                if r.status_code == 200:
                    data = r.json()
                    break
                last_err = f"HTTP {r.status_code} on {url}"
            except Exception as e:
                last_err = f"{type(e).__name__}: {e}"

    if data is None:
        raise HTTPException(
            502,
            f"Spoolman non raggiungibile. Tentativi: {attempted}  Errore: {last_err}"
        )

    # normalizza results -> lista
    if isinstance(data, dict):
        spools = data.get("results") or data.get("spools") or []
    elif isinstance(data, list):
        spools = data
    else:
        spools = []

    def as_float(x):
        try:
            return float(x)
        except Exception:
            return None

    out = []
    for s in spools:
        # s, fil e material possono cambiare tra versioni -> prendiamo il possibile
        fil = s.get("filament", {}) if isinstance(s, dict) else {}

        # materiale
        mat = None
        if isinstance(fil.get("material"), dict):
            mat = fil["material"].get("name")
        else:
            mat = fil.get("material") or s.get("material")
        mat = mat or "N/D"

        # colore (nome + hex)
        color_name = (
            fil.get("color_name") or fil.get("colour_name")
            or (s.get("color") or {}).get("name")
            or s.get("color_name") or s.get("name")
            or "—"
        )
        color_hex = (
            fil.get("color_hex") or fil.get("colour_hex")
            or (s.get("color") or {}).get("hex")
            or s.get("color_hex") or "#777777"
        )

        # prezzo/kg (se presente)
        price_per_kg = (
            s.get("price_per_kg") or s.get("cost_per_kg")
            or fil.get("price_per_kg") or fil.get("cost_per_kg")
        )

        out.append({
            "material": str(mat),
            "color_name": str(color_name),
            "color_hex": str(color_hex),
            "price_per_kg": as_float(price_per_kg),
        })

    out.sort(key=lambda x: (x["material"].lower(), x["color_name"].lower()))
    return JSONResponse(out)

# === Esempio slicing ===
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
