from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import os, tempfile, subprocess, re
import httpx

app = FastAPI(title="slicer-api", version="0.6.0")

# ---- UI ----
app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")

@app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
def health():
    return "ok"

# ---- Config “come prima” ----
CURRENCY    = os.getenv("CURRENCY", "EUR")
HOURLY_RATE = float(os.getenv("HOURLY_RATE", "1"))

def _no_cache(payload: dict):
    return JSONResponse(content=payload, headers={"Cache-Control":"no-store, max-age=0"})

# ---------- Spoolman bridge (robusto) ----------
# Env:
#   SPOOLMAN_URL              es. http://192.168.10.164:7912  oppure https://...
#   SPOOLMAN_TOKEN            (opz) Bearer token
#   SPOOLMAN_SPOOLS_PATH      (opz) path preciso se custom
#   SPOOLMAN_SKIP_TLS_VERIFY  "1/true" per saltare verifica certificato

def _bases_from_env():
    base_env = (os.getenv("SPOOLMAN_URL") or "").rstrip("/")
    if not base_env:
        # fallback identico al vecchio codice
        base_env = "http://192.168.10.164:7912"
    if base_env.startswith("http://") or base_env.startswith("https://"):
        proto, rest = base_env.split("://", 1)
        alt = ("https" if proto == "http" else "http") + "://" + rest
        return [base_env, alt]
    return [f"http://{base_env}", f"https://{base_env}"]

def _paths_from_env():
    over = os.getenv("SPOOLMAN_SPOOLS_PATH")
    return [over] if over else [
        "/api/v1/spool/?page_size=1000",
        "/api/v1/spools?page_size=1000",
        "/api/spool/?page_size=1000",
        "/api/spools?page_size=1000",
    ]

def _first(d: dict, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]

def _ensure_color_hex(v):
    if not v: return None
    s = str(v)
    return s if s.startswith("#") else f"#{s}"

TRANSPARENT_PAT = re.compile(r"\b(clear|transparent|traspar|glass|smoke)\b", re.I)
def _detect_transparent(spool, filament):
    txt = " ".join([
        str(spool.get("color","")),
        str(filament.get("name","")),
        str(filament.get("material",""))
    ])
    return bool(TRANSPARENT_PAT.search(txt))

def _price_per_kg_from_spool(spool, filament):
    spool_price = _first(spool, ["purchase_price","price","spool_price","cost_eur","cost"])
    weight_g    = _first(filament, ["weight","weight_g"])
    if spool_price is not None and weight_g:
        try:
            return float(spool_price) / (float(weight_g) / 1000.0)
        except ZeroDivisionError:
            return None
    # fallback su meta varie
    return _first(filament, ["price_per_kg","cost_per_kg"])

def _extract_filament_from_spool(spool):
    f = spool.get("filament")
    if isinstance(f, dict) and f:
        return f
    fid = _first(spool, ["filament_id","filamentId"])
    if fid:
        # prova a leggere il filament by id sui vari base
        verify = not (os.getenv("SPOOLMAN_SKIP_TLS_VERIFY","").lower() in ("1","true","yes"))
        token  = os.getenv("SPOOLMAN_TOKEN")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        for b in _bases_from_env():
            url = f"{b}/api/v1/filament/{fid}"
            try:
                r = httpx.get(url, timeout=8, headers=headers, verify=verify, follow_redirects=True)
                if r.status_code == 200:
                    return r.json()
            except Exception:
                pass
    # legacy flatten
    legacy = {}
    for k in ("filament_name","name","product"):
        if spool.get(k): legacy["name"] = spool[k]; break
    for k in ("filament_material","material"):
        if spool.get(k): legacy["material"] = spool[k]; break
    for k in ("filament_diameter","diameter","diameter_mm"):
        if spool.get(k): legacy["diameter"] = spool[k]; break
    for k in ("filament_color_hex","color_hex"):
        if spool.get(k): legacy["color_hex"] = spool[k]; break
    for k in ("filament_price","price"):
        if spool.get(k) is not None: legacy["price"] = spool[k]; break
    for k in ("filament_weight","weight_g","weight"):
        if spool.get(k) is not None: legacy["weight"] = spool[k]; break
    return legacy if legacy else {}

@app.get("/inventory")
async def inventory():
    verify = not (os.getenv("SPOOLMAN_SKIP_TLS_VERIFY","").lower() in ("1","true","yes"))
    token  = os.getenv("SPOOLMAN_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    attempted, data, last_err = [], None, None
    async with httpx.AsyncClient(timeout=12.0, headers=headers, follow_redirects=True, verify=verify) as client:
        for b in _bases_from_env():
            for p in _paths_from_env():
                if not p: continue
                url = f"{b}{p}"
                attempted.append(url)
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        break
                    last_err = f"HTTP {r.status_code} on {url}"
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
            if data is not None:
                break

    if data is None:
        raise HTTPException(502, f"Spoolman non raggiungibile. Tentativi: {attempted}  Errore: {last_err}")

    # normalizza lista spool
    spools = data.get("results") or data.get("spools") if isinstance(data, dict) else data
    spools = spools or []

    items = []
    for s in spools:
        f = _extract_filament_from_spool(s)
        color_hex = _ensure_color_hex(_first(s,["color_hex"]) or f.get("color_hex")) or "#777777"
        material  = f.get("material") or "N/A"
        diameter  = str(f.get("diameter") or "")
        is_trans  = _detect_transparent(s, f)
        price_per_kg = _price_per_kg_from_spool(s, f)

        items.append({
            "color_hex": color_hex,
            "material": material,
            "diameter": diameter,
            "count": 1,
            "remaining_g": float(_first(s,["remaining_weight","remaining_weight_g"]) or 0.0),
            "price_per_kg": float(price_per_kg) if price_per_kg is not None else None,
            "currency": CURRENCY,
            "is_transparent": is_trans,
            "color_name": "Trasparente" if is_trans else None
        })

    # merge per (color_hex, material, diameter, is_transparent)
    merged = {}
    for it in items:
        key = (it["color_hex"], it["material"], it["diameter"], it["is_transparent"])
        b = merged.setdefault(key, {"count":0,"remaining_g":0.0,"price_per_kg":None,
                                    "color_hex":it["color_hex"],"material":it["material"],
                                    "diameter":it["diameter"],"is_transparent":it["is_transparent"],
                                    "color_name":it["color_name"],"currency":CURRENCY})
        b["count"] += 1
        b["remaining_g"] += it["remaining_g"]
        if it["price_per_kg"] and not b["price_per_kg"]:
            b["price_per_kg"] = it["price_per_kg"]

    out = list(merged.values())
    out.sort(key=lambda x: (x["material"].lower(), x["color_hex"]))
    return _no_cache({"items": out, "hourly_rate": HOURLY_RATE, "currency": CURRENCY})

# ---- slicing demo (lasciamo PrusaSlicer headless come avevi nel nuovo container) ----
@app.post("/api/slice", response_class=PlainTextResponse)
async def slice_model(
    model: UploadFile = File(...),
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
            "PrusaSlicer","--export-gcode",
            "--load","/profiles/print.ini",
            "--load","/profiles/filament.ini",
            "--load","/profiles/printer.ini",
            in_path,"-o",out_path,
        ]
        if preset_print:    args += ["--load", preset_print]
        if preset_filament: args += ["--load", preset_filament]
        if preset_printer:  args += ["--load", preset_printer]

        try:
            cp = subprocess.run(args, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            tail = (e.stderr or e.stdout or "")[-4000:]
            raise HTTPException(500, f"Slicer failed:\n{tail}")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as g:
            return g.read()

# Retrocompat alias: la tua UI vecchia chiama /inventory, non /api/spools
@app.get("/api/spools")
async def api_spools_alias():
    # per chi stava già puntando qua
    res = await inventory()
    return res
