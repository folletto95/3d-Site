import os, re, io, uuid, zipfile, string
from pathlib import Path
import requests
from fastapi import FastAPI, HTTPException, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

app = FastAPI(title="Spoolsite API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
)

# ---- Config ----
SPOOLMAN_BASE = os.getenv("SPOOLMAN_URL", "http://192.168.10.164:7912").rstrip("/")
API_V1 = f"{SPOOLMAN_BASE}/api/v1"
CURRENCY = os.getenv("CURRENCY", "EUR")
HOURLY_RATE = float(os.getenv("HOURLY_RATE", "1"))

UPLOAD_ROOT = Path("/app/uploads")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(UPLOAD_ROOT)), name="files")

# ---- Utils ----
def _no_cache(payload: dict):
    return JSONResponse(content=payload, headers={"Cache-Control": "no-store, max-age=0"})

def _get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Errore contattando Spoolman: {e}")

def _ensure_color_hex(v):
    """Return a normalized #RRGGBB hex string or None when invalid."""
    if not v:
        return None
    s = str(v).strip().lower()
    if not s:
        return None
    if s.startswith("0x"):
        s = s[2:]
    if s.startswith("#"):
        s = s[1:]
    if len(s) in (3, 4):
        if all(c in string.hexdigits.lower() for c in s):
            # Handle short notation #rgb or #rgba → expand rgb and drop alpha
            s = "".join(ch * 2 for ch in s[:3])
        else:
            return None
    elif len(s) in (6, 8):
        if not all(c in string.hexdigits.lower() for c in s):
            return None
        if len(s) == 8:
            s = s[:6]
    else:
        return None
    return f"#{s.upper()}"


def _extract_color_label(*values):
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        if not text:
            continue
        if _ensure_color_hex(text):
            # Pure hex values are handled separately; keep looking for a human label
            continue
        return text
    return None

def _first(d: dict, keys):
    if not isinstance(d, dict):
        return None
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _extract_color_hex(spool: dict, filament: dict):
    candidates = [
        _first(spool, [
            "color_hex",
            "colour_hex",
            "colorHex",
            "colourHex",
            "filament_color_hex",
            "filament_colour_hex",
        ]),
        _first(filament, ["color_hex", "colour_hex", "colorHex", "colourHex"]),
        _first(spool, ["color", "colour"]),
        _first(filament, ["color", "colour"]),
    ]
    for candidate in candidates:
        hex_value = _ensure_color_hex(candidate)
        if hex_value:
            return hex_value
    return None

def _price_per_kg_from_filament(f):
    price = _first(f, ["price"])
    weight_g = _first(f, ["weight", "weight_g"])
    if price is None or not weight_g:
        return None
    try:
        return float(price) / (float(weight_g) / 1000.0)
    except ZeroDivisionError:
        return None

def _price_per_kg_from_spool(spool, filament):
    spool_price = _first(spool, ["purchase_price", "price", "spool_price", "cost_eur", "cost"])
    weight_g = _first(filament, ["weight", "weight_g"])
    if spool_price is not None and weight_g:
        try:
            return float(spool_price) / (float(weight_g) / 1000.0)
        except ZeroDivisionError:
            pass
    return _price_per_kg_from_filament(filament)

TRANSPARENT_PAT = re.compile(
    r"(transparent|translucent|clear|crystal|glass|natural|natura|traspar|trasluc|neutro)",
    re.I
)
def _detect_transparent(spool: dict, filament: dict):
    txt = " ".join([
        str(spool.get("name","")),
        str(spool.get("product","")),
        str(spool.get("color","")),
        str(filament.get("name","")),
        str(filament.get("material",""))
    ])
    return bool(TRANSPARENT_PAT.search(txt))

def _extract_filament_from_spool(spool):
    f = spool.get("filament")
    if isinstance(f, dict) and f:
        return f
    fid = _first(spool, ["filament_id", "filamentId"])
    if fid:
        return _get(f"{API_V1}/filament/{fid}")
    legacy = {}
    for k in ("filament_name", "name", "product"):
        if spool.get(k): legacy["name"] = spool[k]; break
    for k in ("filament_material", "material"):
        if spool.get(k): legacy["material"] = spool[k]; break
    for k in ("filament_diameter", "diameter", "diameter_mm"):
        if spool.get(k): legacy["diameter"] = spool[k]; break
    for k in ("filament_color_hex", "color_hex"):
        if spool.get(k): legacy["color_hex"] = spool[k]; break
    for k in ("filament_price", "price"):
        if spool.get(k) is not None: legacy["price"] = spool[k]; break
    for k in ("filament_weight", "weight_g", "weight"):
        if spool.get(k) is not None: legacy["weight"] = spool[k]; break
    return legacy if legacy else {}

# ---- Routes base/UI ----
@app.get("/")
def root():
    return RedirectResponse("/ui")

@app.get("/ui")
def ui():
    return FileResponse("/app/web/index.html")

@app.get("/health")
def health():
    return {"ok": True}

# ---- API normalizzate (dati da BOBINE) ----
@app.get("/spools")
def spools():
    sp = _get(f"{API_V1}/spool", params={"allow_archived": False, "limit": 1000})
    out = []
    for s in sp:
        f = _extract_filament_from_spool(s)
        color_hex = _extract_color_hex(s, f) or "#777777"
        is_transparent = _detect_transparent(s, f)
        color_label = _extract_color_label(
            _first(s, ["color_name", "colour_name"]),
            _first(f, ["color_name", "colour_name"]),
            _first(s, ["color", "colour"]),
            _first(f, ["color", "colour"]),
        )
        if is_transparent:
            color_label = color_label or "Trasparente"
        price_per_kg = _price_per_kg_from_spool(s, f)
        out.append({
            "id": s.get("id"),
            "product": f.get("name"),
            "material": f.get("material"),
            "diameter_mm": f.get("diameter"),
            "color_hex": color_hex,
            "is_transparent": is_transparent,
            "color_name": color_label,
            "remaining_weight_g": _first(s, ["remaining_weight", "remaining_weight_g"]),
            "remaining_length_m": (float(_first(s, ["remaining_length"])) / 1000.0) if _first(s, ["remaining_length"]) else None,
            "price_per_kg": price_per_kg,
            "currency": CURRENCY,
            "archived": s.get("archived", False),
            "spool_price_eur": _first(s, ["purchase_price", "price", "spool_price", "cost_eur", "cost"]),
        })
    return _no_cache({"items": out, "hourly_rate": HOURLY_RATE, "currency": CURRENCY})

@app.get("/inventory")
def inventory():
    """
    Aggrego per (colore, materiale, diametro, is_transparent) così
    #FFFFFF (bianco) e #FFFFFF (trasparente) restano voci distinte.
    Prezzo = MIN €/kg tra le bobine del bucket.
    """
    sp = _get(f"{API_V1}/spool", params={"allow_archived": False, "limit": 1000})
    buckets = {}
    for s in sp:
        f = _extract_filament_from_spool(s)
        color_hex = _extract_color_hex(s, f) or "#777777"
        material = f.get("material") or "N/A"
        diameter = str(f.get("diameter") or "")
        is_transparent = _detect_transparent(s, f)
        color_label = _extract_color_label(
            _first(s, ["color_name", "colour_name"]),
            _first(f, ["color_name", "colour_name"]),
            _first(s, ["color", "colour"]),
            _first(f, ["color", "colour"]),
        )
        if is_transparent:
            color_label = color_label or "Trasparente"

        key = (color_hex, material, diameter, is_transparent)
        b = buckets.setdefault(key, {"count": 0, "remaining_g": 0.0, "price_per_kg": None, "color_name": None})
        b["count"] += 1
        rw = _first(s, ["remaining_weight", "remaining_weight_g"])
        if rw is not None:
            b["remaining_g"] += float(rw)
        ppk = _price_per_kg_from_spool(s, f)
        if ppk is not None and (b["price_per_kg"] is None or ppk < b["price_per_kg"]):
            b["price_per_kg"] = ppk
        if color_label and not b["color_name"]:
            b["color_name"] = color_label

    items = []
    for (color, material, diameter, is_transparent), data in buckets.items():
        items.append({
            "key": f"{color}|{material}|{diameter}|{'T' if is_transparent else 'N'}",
            "color": color,
            "material": material,
            "diameter_mm": float(diameter) if diameter not in ("", "None") else None,
            "count": data["count"],
            "remaining_g": round(data["remaining_g"], 1),
            "price_per_kg": data["price_per_kg"],
            "currency": CURRENCY,
            "is_transparent": is_transparent,
            "color_name": data.get("color_name") or ("Trasparente" if is_transparent else None)
        })
    return _no_cache({"items": items, "hourly_rate": HOURLY_RATE, "currency": CURRENCY})

# ---- Upload / Download modelli ----
ALLOWED_EXT = {".stl", ".obj", ".3mf", ".zip"}

def _find_model_in_dir(root: Path):
    order = [".3mf", ".stl", ".obj"]
    best = None
    for ext in order:
        for p in root.rglob(f"*{ext}"):
            best = p; break
        if best: break
    return best

@app.post("/upload_model")
async def upload_model(file: UploadFile = File(...)):
    name = file.filename or "model"
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(status_code=400, detail=f"Estensione non supportata: {ext}")
    uid = uuid.uuid4().hex
    work = UPLOAD_ROOT / uid
    work.mkdir(parents=True, exist_ok=True)
    target = work / name
    data = await file.read()
    target.write_bytes(data)

    model_path = target
    if ext == ".zip":
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            z.extractall(work)
        m = _find_model_in_dir(work)
        if not m:
            raise HTTPException(status_code=400, detail="ZIP senza STL/OBJ/3MF")
        model_path = m

    rel = model_path.relative_to(UPLOAD_ROOT).as_posix()
    return _no_cache({"viewer_url": f"/files/{rel}", "filename": model_path.name})

@app.post("/fetch_model")
def fetch_model(payload: dict = Body(...)):
    url = str(payload.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL mancante")

    uid = uuid.uuid4().hex
    work = UPLOAD_ROOT / uid
    work.mkdir(parents=True, exist_ok=True)

    def _download(u, out_path):
        r = requests.get(u, timeout=15, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1024 * 64):
                if chunk: f.write(chunk)
        return r.headers.get("Content-Type","").lower()

    try:
        ext = Path(url).suffix.lower()
        dst = work / f"remote{ext if ext in ALLOWED_EXT else ''}"
        ctype = _download(url, dst)
        if "text/html" in ctype or dst.suffix.lower() not in ALLOWED_EXT:
            html = dst.read_text(errors="ignore")
            m = re.search(r'https?://[^"\']+\.(?:3mf|stl|obj|zip)', html, re.I)
            if not m:
                raise HTTPException(status_code=400, detail="Nessun link a STL/OBJ/3MF/ZIP trovato nella pagina")
            ext2 = Path(m.group(0)).suffix.lower()
            dst = work / f"remote{ext2}"
            _download(m.group(0), dst)

        model_path = dst
        if dst.suffix.lower() == ".zip":
            with zipfile.ZipFile(dst) as z:
                z.extractall(work)
            m = _find_model_in_dir(work)
            if not m:
                raise HTTPException(status_code=400, detail="ZIP remoto senza STL/OBJ/3MF")
            model_path = m

        rel = model_path.relative_to(UPLOAD_ROOT).as_posix()
        return _no_cache({"viewer_url": f"/files/{rel}", "filename": model_path.name})
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Download fallito: {e}")
