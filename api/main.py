import math
import os, re, io, uuid, zipfile
from pathlib import Path
from typing import List

import requests
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

import trimesh

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
    if not v: return None
    return v if str(v).startswith("#") else f"#{v}"

def _first(d: dict, keys):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None

def _safe_float(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        out = float(value)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return None
        out = float(text)
        if math.isnan(out) or math.isinf(out):
            return None
        return out
    except (TypeError, ValueError):
        return None


def _price_per_kg_from_filament(f):
    price = _safe_float(_first(f, ["price"]))
    weight_g = _safe_float(_first(f, ["weight", "weight_g"]))
    if price is None or weight_g in (None, 0.0):
        return None
    try:
        return price / (weight_g / 1000.0)
    except ZeroDivisionError:
        return None


def _price_per_kg_from_spool(spool, filament):
    spool_price = _safe_float(_first(spool, ["purchase_price", "price", "spool_price", "cost_eur", "cost"]))
    weight_g = _safe_float(_first(filament, ["weight", "weight_g"]))
    if spool_price is not None and weight_g not in (None, 0.0):
        try:
            return spool_price / (weight_g / 1000.0)
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


SPOOL_HINT_KEYS = {
    "remaining_weight",
    "remaining_weight_g",
    "remaining_length",
    "archived",
    "filament",
    "filament_id",
    "filamentId",
    "purchase_price",
    "spool_price",
    "cost",
    "cost_eur",
}


def _as_spool_list(payload) -> List[dict]:
    found: List[dict] = []

    def visit(node):
        if isinstance(node, dict):
            if any(k in node for k in SPOOL_HINT_KEYS):
                found.append(node)
                return
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    visit(payload)
    return [s for s in found if isinstance(s, dict)]


def _fetch_spool_payload(params) -> List[dict]:
    last_exc = None
    for path in ("spool", "spools"):
        try:
            raw = _get(f"{API_V1}/{path}", params=params)
            items = _as_spool_list(raw)
            if items:
                dedup = []
                seen = set()
                for item in items:
                    ident = item.get("id")
                    if ident is not None:
                        if ident in seen:
                            continue
                        seen.add(ident)
                    dedup.append(item)
                return dedup
            if isinstance(raw, dict):
                if any(isinstance(v, list) for v in raw.values()):
                    return []
                if not raw:
                    return []
            if isinstance(raw, list):
                return []
        except HTTPException as exc:
            last_exc = exc
    if last_exc:
        raise last_exc
    return []


def _unit_to_mm(unit: str) -> float:
    unit = (unit or "mm").strip().lower()
    if unit in ("mm", "millimeter", "millimetre"):
        return 1.0
    if unit in ("cm", "centimeter", "centimetre"):
        return 10.0
    if unit in ("m", "meter", "metre"):
        return 1000.0
    if unit in ("in", "inch", "inches"):
        return 25.4
    if unit in ("ft", "feet", "foot"):
        return 304.8
    return 1.0


def _analyze_model(path: Path):
    try:
        mesh = trimesh.load(str(path), force="mesh", skip_materials=True)
    except Exception as exc:  # pragma: no cover - trimesh specific failures
        return {"error": f"Analisi modello fallita: {exc}"}

    if mesh is None or getattr(mesh, "is_empty", False):
        return {"error": "Mesh vuota o non supportata"}

    unit = getattr(mesh, "units", "mm")
    mm_scale = float(_unit_to_mm(unit))

    volume_raw = float(getattr(mesh, "volume", 0.0) or 0.0)
    area_raw = float(getattr(mesh, "area", 0.0) or 0.0)
    watertight = bool(getattr(mesh, "is_watertight", False))

    approx_volume = False
    volume_mm3 = volume_raw * (mm_scale ** 3)
    if (not volume_mm3 or math.isclose(volume_mm3, 0.0)) and hasattr(mesh, "convex_hull"):
        try:
            volume_mm3 = float(mesh.convex_hull.volume) * (mm_scale ** 3)
            approx_volume = True
        except Exception:
            volume_mm3 = 0.0

    area_mm2 = area_raw * (mm_scale ** 2)

    bbox = getattr(mesh, "bounding_box_oriented", None)
    if bbox is not None:
        extents = [float(v) * mm_scale for v in bbox.extents]
    else:
        extents = [float(v) * mm_scale for v in getattr(mesh, "extents", [0.0, 0.0, 0.0])]

    triangles = 0
    try:
        triangles = int(getattr(mesh, "faces", []).__len__())
    except Exception:
        triangles = 0

    centroid = [0.0, 0.0, 0.0]
    if hasattr(mesh, "centroid"):
        centroid = [float(c) * mm_scale for c in mesh.centroid]

    return {
        "units": unit,
        "scale_to_mm": mm_scale,
        "volume_mm3": volume_mm3,
        "surface_area_mm2": area_mm2,
        "is_watertight": watertight,
        "approximate_volume": approx_volume,
        "triangle_count": triangles,
        "bbox_mm": [float(x) for x in extents],
        "centroid_mm": centroid,
    }

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
    sp = _fetch_spool_payload({"allow_archived": False, "limit": 1000})
    out = []
    for s in sp:
        f = _extract_filament_from_spool(s)
        color_hex = _ensure_color_hex(_first(s, ["color_hex"]) or f.get("color_hex"))
        is_transparent = _detect_transparent(s, f)
        price_per_kg = _price_per_kg_from_spool(s, f)
        remaining_weight = _safe_float(_first(s, ["remaining_weight", "remaining_weight_g"]))
        remaining_length = _safe_float(_first(s, ["remaining_length"]))
        out.append({
            "id": s.get("id"),
            "product": f.get("name"),
            "material": f.get("material"),
            "diameter_mm": _safe_float(f.get("diameter")),
            "color_hex": color_hex,
            "is_transparent": is_transparent,
            "color_name": "Trasparente" if is_transparent else None,
            "remaining_weight_g": remaining_weight,
            "remaining_length_m": None if remaining_length is None else (remaining_length / 1000.0),
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
    sp = _fetch_spool_payload({"allow_archived": False, "limit": 1000})
    buckets = {}
    for s in sp:
        f = _extract_filament_from_spool(s)
        color_hex = _ensure_color_hex(_first(s, ["color_hex"]) or f.get("color_hex")) or "#777777"
        material = f.get("material") or "N/A"
        diameter_val = _safe_float(f.get("diameter"))
        diameter = "" if diameter_val is None else f"{diameter_val:g}"
        is_transparent = _detect_transparent(s, f)

        key = (color_hex, material, diameter, is_transparent)
        b = buckets.setdefault(key, {"count": 0, "remaining_g": 0.0, "price_per_kg": None})
        b["count"] += 1
        rw = _safe_float(_first(s, ["remaining_weight", "remaining_weight_g"]))
        if rw is not None:
            b["remaining_g"] += rw
        ppk = _price_per_kg_from_spool(s, f)
        if ppk is not None and (b["price_per_kg"] is None or ppk < b["price_per_kg"]):
            b["price_per_kg"] = ppk

    items = []
    for (color, material, diameter, is_transparent), data in buckets.items():
        diameter_float = _safe_float(diameter)
        items.append({
            "key": f"{color}|{material}|{diameter}|{'T' if is_transparent else 'N'}",
            "color": color,
            "material": material,
            "diameter_mm": diameter_float,
            "count": data["count"],
            "remaining_g": round(data["remaining_g"], 1),
            "price_per_kg": data["price_per_kg"],
            "currency": CURRENCY,
            "is_transparent": is_transparent,
            "color_name": "Trasparente" if is_transparent else None
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
    analysis = _analyze_model(model_path)
    return _no_cache({
        "viewer_url": f"/files/{rel}",
        "filename": model_path.name,
        "analysis": analysis,
    })

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
        analysis = _analyze_model(model_path)
        return _no_cache({
            "viewer_url": f"/files/{rel}",
            "filename": model_path.name,
            "analysis": analysis,
        })
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Download fallito: {e}")
