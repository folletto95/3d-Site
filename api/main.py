import os, re, io, uuid, zipfile, subprocess, json
from functools import lru_cache
from pathlib import Path
import math
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
#
# Spoolsite needs to communicate with Spoolman to read filament inventory.  When run via
# docker‑compose the `SPOOLMAN_URL` environment variable should be set to the container
# hostname (e.g. "http://spoolman:7912").  However, when running this API outside of
# docker on a local network we fall back to the original hard‑coded IP address.  This
# ensures that existing installs continue to reach the user's Spoolman instance without
# requiring changes to environment variables.  See README for details.
SPOOLMAN_BASE = os.getenv("SPOOLMAN_URL", "http://192.168.10.164:7912").rstrip("/")
API_V1 = f"{SPOOLMAN_BASE}/api/v1"
CURRENCY = os.getenv("CURRENCY", "EUR")
HOURLY_RATE = float(os.getenv("HOURLY_RATE", "1"))

UPLOAD_ROOT = Path("/app/uploads")
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(UPLOAD_ROOT)), name="files")

# ---- Utils generiche ----
def _no_cache(payload: dict):
    return JSONResponse(content=payload, headers={"Cache-Control": "no-store, max-age=0"})

def _get(url, params=None):
    try:
        r = requests.get(url, params=params, timeout=12)
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

# ---- Prezzi €/kg (server-side) da bobine ----
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

# ---- Trasparente vs Bianco ----
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

# ---- Builder inventario (riusato da /inventory e /slice/estimate) ----
def _build_inventory_items():
    sp = _get(f"{API_V1}/spool", params={"allow_archived": False, "limit": 1000})
    buckets = {}
    for s in sp:
        f = _extract_filament_from_spool(s)
        color_hex = _ensure_color_hex(_first(s, ["color_hex"]) or f.get("color_hex")) or "#777777"
        material = f.get("material") or "N/A"
        diameter = str(f.get("diameter") or "")
        is_transparent = _detect_transparent(s, f)

        key = (color_hex, material, diameter, is_transparent)
        b = buckets.setdefault(key, {"count": 0, "remaining_g": 0.0, "price_per_kg": None})
        b["count"] += 1
        rw = _first(s, ["remaining_weight", "remaining_weight_g"])
        if rw is not None:
            b["remaining_g"] += float(rw)
        ppk = _price_per_kg_from_spool(s, f)
        if ppk is not None and (b["price_per_kg"] is None or ppk < b["price_per_kg"]):
            b["price_per_kg"] = ppk

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
            "color_name": "Trasparente" if is_transparent else None
        })
    return items

# ---- Rotazioni (compat futura per Cura >=5) ----
def _identity3():
    return [[1,0,0],[0,1,0],[0,0,1]]

def _is_3x3_numeric(M):
    try:
        return (
            isinstance(M, (list, tuple)) and len(M) == 3 and
            all(isinstance(r, (list, tuple)) and len(r) == 3 for r in M) and
            all(all(isinstance(x, (int, float)) for x in r) for r in M)
        )
    except Exception:
        return False

def _deg2rad(d): return d * math.pi / 180.0
def _matmul3(A, B):
    return [
        [A[0][0]*B[0][j] + A[0][1]*B[1][j] + A[0][2]*B[2][j] for j in range(3)],
        [A[1][0]*B[0][j] + A[1][1]*B[1][j] + A[1][2]*B[2][j] for j in range(3)],
        [A[2][0]*B[0][j] + A[2][1]*B[1][j] + A[2][2]*B[2][j] for j in range(3)],
    ]
def _rot_x(deg):
    a = _deg2rad(deg); c, s = math.cos(a), math.sin(a)
    return [[1,0,0],[0,c,-s],[0,s,c]]
def _rot_y(deg):
    a = _deg2rad(deg); c, s = math.cos(a), math.sin(a)
    return [[c,0,s],[0,1,0],[-s,0,c]]
def _rot_z(deg):
    a = _deg2rad(deg); c, s = math.cos(a), math.sin(a)
    return [[c,-s,0],[s,c,0],[0,0,1]]

def _parse_rotation_from_settings(settings: dict):
    M = settings.get("mesh_rotation_matrix")
    if _is_3x3_numeric(M):
        return M
    e = settings.get("mesh_rotation_euler_deg")
    if e is not None:
        if isinstance(e, dict):
            x = float(e.get("x", 0)); y = float(e.get("y", 0)); z = float(e.get("z", 0))
            order = (e.get("order") or "XYZ").upper()
        elif isinstance(e, (list, tuple)) and len(e) == 3:
            x, y, z = map(float, e); order = (settings.get("mesh_rotation_order") or "XYZ").upper()
        else:
            x = y = z = 0.0; order = "XYZ"
        R = _identity3()
        rot_map = {"X": _rot_x, "Y": _rot_y, "Z": _rot_z}
        angles = {"X": x, "Y": y, "Z": z}
        for ax in order:
            if ax in rot_map:
                R = _matmul3(R, rot_map[ax](angles[ax]))
        return R
    p = settings.get("mesh_rotation_preset")
    if isinstance(p, str) and p.strip():
        R = _identity3()
        for token in p.replace(" ", "").split("+"):
            if not token: continue
            ax = token[0].upper()
            try: ang = float(token[1:])
            except ValueError: ang = 0.0
            if   ax == "X": R = _matmul3(R, _rot_x(ang))
            elif ax == "Y": R = _matmul3(R, _rot_y(ang))
            elif ax == "Z": R = _matmul3(R, _rot_z(ang))
        return R
    return _identity3()

# ---- Versione Cura nel container ----
@lru_cache()
def _cura_version():
    try:
        cp = subprocess.run(["CuraEngine", "--version"], capture_output=True, text=True, timeout=5)
        out = (cp.stdout or "") + (cp.stderr or "")
        m = re.search(r"(\d+)\.(\d+)\.(\d+)", out)
        if m:
            return tuple(map(int, m.groups()))
    except Exception:
        pass
    return (0,0,0)

def _cura_supports_mesh_rotation():
    major, minor, patch = _cura_version()
    return major >= 5

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

# ---- API Spoolman ----
@app.get("/spools")
def spools():
    sp = _get(f"{API_V1}/spool", params={"allow_archived": False, "limit": 1000})
    out = []
    for s in sp:
        f = _extract_filament_from_spool(s)
        color_hex = _ensure_color_hex(_first(s, ["color_hex"]) or f.get("color_hex"))
        is_transparent = _detect_transparent(s, f)
        price_per_kg = _price_per_kg_from_spool(s, f)
        out.append({
            "id": s.get("id"),
            "product": f.get("name"),
            "material": f.get("material"),
            "diameter_mm": f.get("diameter"),
            "color_hex": color_hex,
            "is_transparent": is_transparent,
            "color_name": "Trasparente" if is_transparent else None,
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
    items = _build_inventory_items()
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
        r = requests.get(u, timeout=20, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(1024 * 64):
                if chunk: f.write(chunk)
        return r.headers.get("Content-Type","" ).lower()

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

# =========================
#      SLICER (CuraEngine)
# =========================

# densità tipiche (g/cm3)
DENSITY = {
    "PLA": 1.24, "PETG": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.20,
    "NYLON": 1.14, "PA": 1.14, "PC": 1.20, "PET": 1.38
}
def _density_for(material: str):
    if not material: return 1.24
    m = material.upper()
    for k,v in DENSITY.items():
        if k in m: return v
    return 1.24

def _grams_from_length_mm(length_mm: float, diameter_mm: float, density_g_cm3: float):
    area_mm2 = math.pi * (diameter_mm/2.0)**2
    vol_mm3 = area_mm2 * length_mm
    vol_cm3 = vol_mm3 / 1000.0
    return vol_cm3 * density_g_cm3

def _grams_from_volume_mm3(vol_mm3: float, density_g_cm3: float):
    return (vol_mm3 / 1000.0) * density_g_cm3

def _parse_cura_filament_usage(text: str, diameter_mm: float, density_g_cm3: float):
    """
    Ritorna (filament_g, filament_mm).
    Somma tutte le occorrenze trovate (multi-estrusore).
    Supporta:
      ;Filament used: 12.3m|mm|cm|g
      ;Filament used [g]: 12.3
      ;Filament used [mm^3]: 12345.6   (o [mm3], [cm^3], [cm3])
    """
    total_g = 0.0
    total_len_mm = 0.0
    total_vol_mm3 = 0.0

    # 1) "Filament used: <val><unit>"
    for m in re.finditer(r";\s*Filament used\s*:\s*([\d\.]+)\s*([a-zA-Z0-9\^\[\]]+)", text, re.I):
        val = float(m.group(1))
        unit = m.group(2).strip().lower()
        unit = unit.strip("[]")  # in caso sia tipo [g]
        if unit in ("g",):
            total_g += val
        elif unit in ("mm",):
            total_len_mm += val
        elif unit in ("cm",):
            total_len_mm += val * 10.0
        elif unit in ("m",):
            total_len_mm += val * 1000.0
        elif unit in ("mm3", "mm^3"):
            total_vol_mm3 += val
        elif unit in ("cm3", "cm^3"):
            total_vol_mm3 += val * 1000.0

    # 2) "Filament used [unit]: <val>"
    for m in re.finditer(r";\s*Filament used\s*\[\s*([^\]]+)\s*\]\s*:\s*([\d\.]+)", text, re.I):
        unit = m.group(1).strip().lower().replace(" ", "")
        val = float(m.group(2))
        if unit in ("g",):
            total_g += val
        elif unit in ("mm",):
            total_len_mm += val
        elif unit in ("cm",):
            total_len_mm += val * 10.0
        elif unit in ("m",):
            total_len_mm += val * 1000.0
        elif unit in ("mm3", "mm^3"):
            total_vol_mm3 += val
        elif unit in ("cm3", "cm^3"):
            total_vol_mm3 += val * 1000.0

    # 3) fallback "Material used" (alcune build lo usano)
    for m in re.finditer(r";\s*Material used\s*\[\s*([^\]]+)\s*\]\s*:\s*([\d\.]+)", text, re.I):
        unit = m.group(1).strip().lower().replace(" ", "")
        val = float(m.group(2))
        if unit in ("g",):
            total_g += val
        elif unit in ("mm3", "mm^3"):
            total_vol_mm3 += val
        elif unit in ("cm3", "cm^3"):
            total_vol_mm3 += val * 1000.0

    # Preferisci g diretto; altrimenti converti volume; altrimenti lunghezza
    if total_g > 0:
        return total_g, None
    if total_vol_mm3 > 0:
        return _grams_from_volume_mm3(total_vol_mm3, density_g_cm3), None
    if total_len_mm > 0:
        return None, total_len_mm

    return None, None

# ---- Fallback estimator ----
def _estimate_filament_length_from_gcode(gcode_path: Path) -> float:
    """
    Estimate the total extruded filament length (in millimetres) by summing E‑axis moves
    in the G‑code.  This parser handles multi‑extruder and multi‑colour prints by
    tracking extrusion separately per active tool (T0, T1, …).  For each tool it
    assumes absolute extrusion mode and resets the E position on explicit resets
    (G92 or M92 with E0).  Negative movements (retractions) and very large jumps
    are ignored to avoid overcounting.  Returns the sum of all extruded lengths.
    """
    try:
        text = gcode_path.read_text(errors="ignore")
    except Exception:
        return 0.0
    # track total extrusion per tool
    totals: dict[int, float] = {}
    # remember last E coordinate per tool
    last_e: dict[int, float] = {}
    current_tool = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Skip full comment lines
        if line.startswith(";"):
            continue
        # Detect tool change commands (e.g. T0, T1, T2)
        # Only consider tool change if the line starts with 'T' followed by digits
        if line.startswith("T") and len(line) > 1 and line[1].isdigit():
            try:
                current_tool = int(re.match(r"T(\d+)", line).group(1))
            except Exception:
                current_tool = 0
            # Ensure structures exist for the new tool
            totals.setdefault(current_tool, 0.0)
            last_e.setdefault(current_tool, None)
            continue
        # Reset extruder position for current tool
        # G92 E0 or M92 E0 resets the E axis
        if ("G92" in line or "M92" in line) and (" E0" in line or " E0.0" in line):
            last_e[current_tool] = 0.0
            continue
        # Find E axis value
        m = re.search(r"E([+-]?\d*\.\d+|[+-]?\d+)", line)
        if not m:
            continue
        try:
            e_val = float(m.group(1))
        except ValueError:
            continue
        # Initialise last_e for this tool if not seen before
        if current_tool not in last_e or last_e[current_tool] is None:
            last_e[current_tool] = e_val
            continue
        diff = e_val - last_e[current_tool]
        # treat retracts or unusual jumps as zero to avoid overcounting
        if diff < 0 or diff > 1000:
            diff = 0.0
        totals[current_tool] = totals.get(current_tool, 0.0) + diff
        last_e[current_tool] = e_val
    # Sum across all tools
    return sum(totals.values())

def _run_cura_slice(model_path: Path, layer_h=0.2, infill=15, nozzle=0.4,
                    filament_diam=1.75, travel_speed=150, print_speed=60,
                    rot_matrix=None):
    out_gcode = model_path.with_suffix(".gcode")
    if rot_matrix is None:
        rot_matrix = _identity3()

    printer_def = Path("/api/cura_defs/fdmprinter.def.json")
    extruder_def = Path("/api/cura_defs/fdmextruder.def.json")

    cura_args = ["CuraEngine", "slice"]

    # Definitions 4.13
    if printer_def.exists():
        cura_args += ["-j", str(printer_def)]
    if extruder_def.exists():
        cura_args += ["-j", str(extruder_def)]

    # Parametri in mm/s (Cura 4.x)
    cura_args += [
        "-l", str(model_path),
        "-o", str(out_gcode),
        "-s", f"layerHeight={layer_h}",
        "-s", f"infill_sparse_density={infill}",
        "-s", f"machine_nozzle_size={nozzle}",
        "-s", f"material_diameter={filament_diam}",
        "-s", f"speed_travel={travel_speed}",
        "-s", f"speed_print={print_speed}",
    ]

    # Solo Cura >=5 supporta mesh_rotation_matrix
    if _cura_supports_mesh_rotation():
        cura_args += ["-s", f"mesh_rotation_matrix={json.dumps(rot_matrix)}"]

    cp = subprocess.run(cura_args, capture_output=True, text=True, timeout=180)
    if cp.returncode != 0:
        raise HTTPException(status_code=500, detail=f"CuraEngine error:\n{cp.stderr or cp.stdout}")

    text = out_gcode.read_text(errors="ignore")

    # parse tempo
    m_time = re.search(r";TIME:(\d+)", text)
    time_s = int(m_time.group(1)) if m_time else None

    # parse filamento robusto (g / mm / mm^3 / cm^3)
    filament_g, filament_mm = _parse_cura_filament_usage(
        text=text,
        diameter_mm=filament_diam,
        density_g_cm3=_density_for("")  # verrà ricalcolato più avanti su materiale
    )

    return {
        "time_s": time_s,
        "filament_mm": filament_mm,
        "filament_g": filament_g,
        "gcode_rel": out_gcode.relative_to(UPLOAD_ROOT).as_posix()
    }

@app.post("/slice/estimate")
def slice_estimate(payload: dict = Body(...)):
    """
    Richiede:
    {
      "viewer_url": "/files/<path_relativo>",
      "inventory_key": "<chiave di /inventory>",
      "settings": {
        "layer_h":0.2, "infill":15, "nozzle":0.4, "print_speed":60, "travel_speed":150,
        # opzionali (attivi solo con Cura >=5):
        "mesh_rotation_matrix": [[1,0,0],[0,1,0],[0,0,1]],
        "mesh_rotation_euler_deg": {"x":90, "y":0, "z":0, "order":"XYZ"},
        "mesh_rotation_preset": "x90+y-90"
      }
    }
    """
    viewer_url = payload.get("viewer_url")
    inv_key = payload.get("inventory_key")
    settings = payload.get("settings") or {}

    if not viewer_url or not viewer_url.startswith("/files/"):
        raise HTTPException(status_code=400, detail="viewer_url non valido")
    rel = viewer_url[len("/files/"):]
    model_path = UPLOAD_ROOT / rel
    if not model_path.exists():
        raise HTTPException(status_code=404, detail="Modello non trovato")

    items = _build_inventory_items()
    bucket = next((x for x in items if x["key"] == inv_key), None)
    if not bucket:
        raise HTTPException(status_code=400, detail="inventory_key non valido")
    price_per_kg = bucket.get("price_per_kg")
    if price_per_kg is None:
        raise HTTPException(status_code=400, detail="Prezzo €/kg non disponibile per il materiale scelto")

    mat = bucket.get("material") or "PLA"
    diam = bucket.get("diameter_mm") or 1.75

    layer_h = float(settings.get("layer_h", 0.2))
    infill = float(settings.get("infill", 15))
    nozzle = float(settings.get("nozzle", 0.4))
    print_speed = float(settings.get("print_speed", 60))    # mm/s
    travel_speed = float(settings.get("travel_speed", 150)) # mm/s

    r = _run_cura_slice(
        model_path=model_path,
        layer_h=layer_h, infill=infill, nozzle=nozzle,
        filament_diam=diam, travel_speed=travel_speed, print_speed=print_speed,
        rot_matrix=_parse_rotation_from_settings(settings)
    )

    time_s = r["time_s"] or 0

    # Densità materiale
    density = _density_for(mat)

    # Priorità: usa i grammi se presenti; altrimenti converti da volume; altrimenti da lunghezza
    filament_g = r["filament_g"]
    filament_mm = r["filament_mm"]

    if filament_g is None and filament_mm is None:
        # tentativo extra: cerca solo volume nel testo (alcune build lo mettono tardi)
        g2, mm2 = _parse_cura_filament_usage(
            text=(UPLOAD_ROOT / r["gcode_rel"]).read_text(errors="ignore"),
            diameter_mm=diam, density_g_cm3=density
        )
        filament_g = g2 if g2 is not None else filament_g
        filament_mm = mm2 if mm2 is not None else filament_mm

    if filament_g is None and filament_mm is not None:
        filament_g = _grams_from_length_mm(filament_mm, diam, density)

    if filament_g is None:
        # Attempt a more expensive fallback by summing E‑axis moves in the generated G‑code.
        # This covers cases where CuraEngine omits the "Filament used" comments entirely.
        try:
            gcode_path = UPLOAD_ROOT / r["gcode_rel"]
            est_len_mm = _estimate_filament_length_from_gcode(gcode_path)
        except Exception:
            est_len_mm = 0.0
        if est_len_mm > 0:
            filament_g = _grams_from_length_mm(est_len_mm, diam, density)
        if filament_g is None:
            raise HTTPException(status_code=500, detail="Impossibile leggere il consumo filamento dallo slicer")

    cost_filament = (filament_g/1000.0) * float(price_per_kg)
    cost_machine  = (time_s/3600.0) * HOURLY_RATE
    total = cost_filament + cost_machine

    return _no_cache({
        "time_s": round(time_s),
        "filament_g": round(filament_g, 1),
        "price_per_kg": round(float(price_per_kg), 2),
        "hourly_rate": HOURLY_RATE,
        "currency": CURRENCY,
        "cost_filament": round(cost_filament, 2),
        "cost_machine": round(cost_machine, 2),
        "total": round(total, 2),
        "gcode_url": f"/files/{r['gcode_rel']}"
    })
