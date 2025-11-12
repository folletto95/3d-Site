from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os, tempfile, subprocess, re, colorsys, json, threading, uuid, math, shutil, shlex
import httpx

app = FastAPI(title="slicer-api", version="0.9.0")

# ---------- UI ----------
app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")

@app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
def health():
    return "ok"

# ---------- Config ----------
def _env_float(name: str, default: float) -> float:
    try:
        v = os.getenv(name)
        if not v:
            return default
        return float(v)
    except Exception:
        return default

def _env_int(name: str, default: int) -> int:
    try:
        v = os.getenv(name)
        if not v:
            return default
        return int(v)
    except Exception:
        return default

# legge SPOOLMAN_BASE oppure SPOOLMAN_URL
SPOOLMAN_BASE = os.getenv("SPOOLMAN_BASE") or os.getenv("SPOOLMAN_URL") or ""
SPOOLMAN_PATHS = os.getenv("SPOOLMAN_PATHS") or "/api/v1/spool/?page_size=1000,/api/v1/spools?page_size=1000,/api/spool/?page_size=1000,/api/spools?page_size=1000"
CURRENCY = os.getenv("CURRENCY", "EUR")
HOURLY_RATE = _env_float("HOURLY_RATE", 1.0)

_HEX_RE = re.compile(r"#?[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?")

def _bases_from_env():
    bases: list[str] = []
    if SPOOLMAN_BASE:
        bases.append(SPOOLMAN_BASE.rstrip("/"))
    for raw in os.getenv("SPOOLMAN_BASES", "").split(","):
        raw = raw.strip()
        if raw:
            bases.append(raw.rstrip("/"))
    bases.append("http://spoolman:7912")
    bases.append("http://192.168.10.164:7912")
    seen: set[str] = set()
    ordered: list[str] = []
    for base in bases:
        if base not in seen:
            ordered.append(base)
            seen.add(base)
    return ordered

def _paths_from_env():
    paths: list[str] = []
    for raw in SPOOLMAN_PATHS.split(","):
        raw = raw.strip()
        if raw:
            if not raw.startswith("/"):
                raw = "/" + raw
            paths.append(raw)
    return list(dict.fromkeys(paths))

def _no_cache(payload: dict) -> JSONResponse:
    return JSONResponse(
        payload,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )

def _first(d: dict, keys: list[str]):
    for k in keys:
        if k in d and d[k] not in (None, ""):
            return d[k]
    return None

def _normalize_hex(h: str | None) -> str | None:
    if not h:
        return None
    s = str(h).strip()
    if not s:
        return None
    if not s.startswith("#"):
        s = "#" + s
    if len(s) == 4:  # #RGB -> #RRGGBB
        r, g, b = s[1], s[2], s[3]
        s = f"#{r}{r}{g}{g}{b}{b}"
    return s.upper()[:7]


def _raw_color_hex(spool: dict, filament: dict) -> str | None:
    def _pick_hex(value) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, (list, tuple, set)):
            for item in value:
                c = _pick_hex(item)
                if c:
                    return c
            return None
        if isinstance(value, dict):
            for key in ("hex", "colour", "color", "value"):
                if key in value:
                    c = _pick_hex(value[key])
                    if c:
                        return c
            return None
        text = str(value)
        m = _HEX_RE.search(text)
        if m:
            return m.group(0)
        return None

    raw = _pick_hex(_first(spool, ["color_hex"])) or _pick_hex(filament.get("color_hex"))
    if raw:
        return raw
    multi = _first(spool, ["multi_color_hexes"]) or filament.get("multi_color_hexes")
    return _pick_hex(multi)


def _weight_from_spool(spool: dict, filament: dict) -> float | None:
    weight_candidates = [
        _first(filament, ["weight", "weight_g"]),
        _first(spool, ["initial_weight", "initial_weight_g"]),
    ]
    for candidate in weight_candidates:
        if candidate in (None, ""):
            continue
        try:
            value = float(candidate)
            if value > 0:
                return value
        except Exception:
            continue
    remaining = _first(spool, ["remaining_weight", "remaining_weight_g"])
    used = spool.get("used_weight")
    try:
        if remaining is not None and used is not None:
            value = float(remaining) + float(used)
            if value > 0:
                return value
    except Exception:
        pass
    return None

# ---------- paths helper ----------
def _guess_web_dir() -> str:
    env = os.getenv("WEB_DIR")
    if env:
        p = os.path.abspath(env)
        if os.path.isdir(p):
            return p
    try:
        cwd = os.getcwd()
        p = os.path.join(cwd, "web")
        if os.path.isdir(p):
            return os.path.abspath(p)
    except Exception:
        pass
    here = os.path.dirname(__file__)
    p = os.path.abspath(os.path.join(here, "..", "..", "web"))
    if os.path.isdir(p):
        return p
    base = here
    for _ in range(4):
        base = os.path.dirname(base)
        if not base or base == os.path.sep:
            break
        p = os.path.join(base, "web")
        if os.path.isdir(p):
            return os.path.abspath(p)
    return os.path.abspath("web")

WEB_DIR = _guess_web_dir()

# --- Mappa colori (colors.json) ---
def _guess_colors_json_path() -> str:
    env = os.getenv("COLORS_JSON_PATH")
    if env:
        return os.path.abspath(env)
    return os.path.join(WEB_DIR, "colors.json")

_COLORS_JSON_PATH = _guess_colors_json_path()
_COLORS_LOCK = threading.Lock()
_COLORS_MAP: dict[str, str] | None = None
_COLORS_DIRTY = False

def _load_colors_map() -> dict[str, str]:
    global _COLORS_MAP
    if _COLORS_MAP is not None:
        return _COLORS_MAP
    cmap: dict[str, str] = {}
    try:
        with open(_COLORS_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for k, v in data.items():
                hk = _normalize_hex(k)
                if hk:
                    cmap[hk] = str(v)
    except FileNotFoundError:
        cmap = {}
    except Exception:
        cmap = {}
    _COLORS_MAP = cmap
    return _COLORS_MAP

def _get_color_from_map(h: str) -> str | None:
    cmap = _load_colors_map()
    hx = _normalize_hex(h)
    if not hx:
        return None
    return cmap.get(hx)

def _register_color_hex(h: str, name: str | None) -> None:
    global _COLORS_DIRTY
    hx = _normalize_hex(h)
    if not hx:
        return
    cmap = _load_colors_map()
    if hx in cmap:
        return
    cmap[hx] = name or ""
    _COLORS_DIRTY = True

def _flush_colors_map_if_dirty() -> None:
    global _COLORS_DIRTY, _COLORS_MAP
    if not _COLORS_DIRTY or _COLORS_MAP is None:
        return
    with _COLORS_LOCK:
        try:
            os.makedirs(os.path.dirname(_COLORS_JSON_PATH), exist_ok=True)
            tmp = _COLORS_JSON_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_COLORS_MAP, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, _COLORS_JSON_PATH)
            _COLORS_DIRTY = False
        except Exception:
            pass

# ---------- Heuristica colore fallback ----------
def _hex_to_name(h: str) -> str:
    h = _normalize_hex(h)
    if not h:
        return "Grigio"
    try:
        r = int(h[1:3], 16) / 255.0
        g = int(h[3:5], 16) / 255.0
        b = int(h[5:7], 16) / 255.0
    except Exception:
        return "Grigio"

    if r > 0.94 and g > 0.94 and b > 0.94:
        return "Bianco"
    if r < 0.06 and g < 0.06 and b < 0.06:
        return "Nero"

    h_, l, s = colorsys.rgb_to_hls(r, g, b)
    deg = (h_ * 360.0) % 360.0

    if s < 0.10:
        if l > 0.90:
            return "Bianco"
        if l < 0.10:
            return "Nero"
        return "Grigio"

    if s < 0.35 and l > 0.75 and (deg < 25 or deg > 320):
        return "Rosa"
    if 15 <= deg < 40 and l < 0.55:
        return "Marrone"
    if 40 <= deg < 55 and s > 0.40 and l > 0.45:
        return "Oro"

    if deg < 12 or deg >= 348: return "Rosso"
    if 12 <= deg < 40:  return "Arancione"
    if 55 <= deg < 75:  return "Giallo"
    if 75 <= deg < 165: return "Verde"
    if 165 <= deg < 190: return "Ciano"
    if 190 <= deg < 250: return "Blu"
    if 250 <= deg < 300: return "Viola"
    if 300 <= deg < 350: return "Rosa"
    return "Grigio"

TRANSPAT = re.compile(
    r"\b(clear|transparent|traspar|translucent|translucido|semi[-\s]?traspar|glass|smoke)\b",
    re.I,
)

def _detect_transparent(spool: dict, filament: dict, color_hex: str | None) -> bool:
    blob = " ".join(
        [
            str(spool.get("name", "")),
            str(spool.get("product", "")),
            str(spool.get("color", "")),
            str(spool.get("color_name", "")),
            str(filament.get("name", "")),
            str(filament.get("material", "")),
        ]
    )
    if TRANSPAT.search(blob):
        return True
    mat = (filament.get("material") or spool.get("material") or "").lower()
    if "petg" in mat and "transluc" in blob.lower():
        return True
    hx = _normalize_hex(color_hex)
    if hx:
        try:
            r = int(hx[1:3], 16)
            g = int(hx[3:5], 16)
            b = int(hx[5:7], 16)
            if max(r, g, b) > 248 and TRANSPAT.search(blob):
                return True
        except Exception:
            pass
    return False

def _extract_filament_from_spool(spool: dict) -> dict:
    f = spool.get("filament") or {}
    if not isinstance(f, dict):
        f = {}
    return f

def _price_per_kg_from_spool(spool: dict, filament: dict) -> float | None:
    spool_price = _first(spool, ["purchase_price", "price", "spool_price", "cost_eur", "cost"])
    weight_g = _weight_from_spool(spool, filament)
    if spool_price is not None and weight_g:
        try:
            return float(spool_price) / (float(weight_g) / 1000.0)
        except Exception:
            return None
    v = _first(filament, ["price_per_kg", "cost_per_kg"])
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None

# ---------- Inventory ----------
@app.get("/inventory")
async def inventory():
    verify = not (os.getenv("SPOOLMAN_SKIP_TLS_VERIFY", "").lower() in ("1", "true", "yes"))
    token = os.getenv("SPOOLMAN_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    attempted: list[str] = []
    data = None
    last_err: str | None = None

    async with httpx.AsyncClient(timeout=12.0, headers=headers, follow_redirects=True, verify=verify) as client:
        for b in _bases_from_env():
            for p in _paths_from_env():
                if not p:
                    continue
                url = f"{b}{p}"
                attempted.append(url)
                try:
                    r = await client.get(url)
                    if r.status_code == 200:
                        data = r.json()
                        break
                    last_err = f"{r.status_code} {r.text[:200]}"
                except Exception as e:
                    last_err = f"{type(e).__name__}: {e}"
            if data is not None:
                break

    if data is None:
        detail = f"Spoolman non raggiungibile. Tentativi: {attempted}"
        if last_err:
            detail += f"  Errore: {last_err}"
        raise HTTPException(502, detail)

    if isinstance(data, dict):
        spools = data.get("results") or data.get("spools") or []
    else:
        spools = data or []

    items: list[dict] = []
    for s in spools:
        f = _extract_filament_from_spool(s)
        color_hex = _normalize_hex(_raw_color_hex(s, f)) or "#777777"
        material = f.get("material") or s.get("material") or "N/A"
        diameter = str(f.get("diameter") or s.get("diameter") or "")
        is_trans = _detect_transparent(s, f, color_hex)

        color_name: str | None = None
        if not is_trans:
            color_name = _get_color_from_map(color_hex)
        if not color_name:
            color_name = _first(s, ["color_name", "colour_name"]) or f.get("color_name") or f.get("colour_name")
        if is_trans:
            color_name = "Trasparente"
        if not color_name:
            color_name = _hex_to_name(color_hex)
        if not color_name:
            color_name = "N/D"

        price_per_kg = _price_per_kg_from_spool(s, f)
        if not is_trans:
            _register_color_hex(color_hex, color_name)

        items.append(
            {
                "hex": color_hex,
                "name": color_name,
                "color_hex": color_hex,
                "color_name": color_name,
                "material": material,
                "diameter": diameter,
                "count": 1,
                "remaining_g": float(_first(s, ["remaining_weight", "remaining_weight_g"]) or 0.0),
                "price_per_kg": float(price_per_kg) if price_per_kg is not None else None,
                "currency": CURRENCY,
                "is_transparent": bool(is_trans),
            }
        )

    merged: dict[tuple[str, str, str, bool], dict] = {}
    for it in items:
        key = (it["hex"], it["material"], it["diameter"], it["is_transparent"])
        b = merged.setdefault(
            key,
            {
                "count": 0,
                "remaining_g": 0.0,
                "price_per_kg": None,
                "hex": it["hex"],
                "name": it["name"],
                "color_hex": it["color_hex"],
                "color_name": it["color_name"],
                "material": it["material"],
                "diameter": it["diameter"],
                "is_transparent": it["is_transparent"],
                "currency": CURRENCY,
            },
        )
        b["count"] += 1
        b["remaining_g"] += it["remaining_g"]
        if it["price_per_kg"] and not b["price_per_kg"]:
            b["price_per_kg"] = it["price_per_kg"]

    out = list(merged.values())
    out.sort(key=lambda x: (x["material"].lower(), x["name"].lower(), x["hex"]))
    _flush_colors_map_if_dirty()
    return _no_cache({"items": out, "hourly_rate": HOURLY_RATE, "currency": CURRENCY})

@app.get("/api/spools")
async def inventory_legacy():
    return await inventory()

# ---------- Upload modello (viewer) ----------
ALLOWED_EXTS = {".stl", ".obj", ".3mf"}

def _safe_filename(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("._")
    if not base:
        base = "model"
    return base

def _guess_uploads_dir() -> str:
    uploads = os.path.join(WEB_DIR, "uploads")
    os.makedirs(uploads, exist_ok=True)
    return uploads

@app.post("/upload_model")
async def upload_model(file: UploadFile = File(...)):
    orig = file.filename or "model"
    ext = os.path.splitext(orig)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(400, f"Estensione non supportata: {ext} (consentiti: {', '.join(sorted(ALLOWED_EXTS))})")

    uploads = _guess_uploads_dir()
    safe = _safe_filename(os.path.splitext(orig)[0]) + "_" + uuid.uuid4().hex[:8] + ext
    out_path = os.path.join(uploads, safe)

    try:
        with open(out_path, "wb") as f:
            chunk = await file.read()
            f.write(chunk)
    except Exception as e:
        raise HTTPException(500, f"Scrittura file fallita: {type(e).__name__}: {e}")

    viewer_url = f"/ui/uploads/{safe}"
    return {"viewer_url": viewer_url, "filename": safe}

# ---------- Estimation ----------
_TIME_PAT = re.compile(r"estimated printing time(?: \(.*?\))?\s*=\s*([^\n\r;]+)", re.I)
_FIL_G_PAT = re.compile(r"filament\s+used\s*\[\s*g\s*\]\s*=\s*([\d.]+)", re.I)
_FIL_MM_PAT = re.compile(r"filament\s+used\s*\[\s*mm\s*\]\s*=\s*([\d.]+)", re.I)

def _parse_time_to_seconds(txt: str) -> int | None:
    s = txt.strip().lower()
    # "1h 23m 45s"
    m = re.findall(r"(\d+)\s*h", s)
    h = int(m[0]) if m else 0
    m2 = re.findall(r"(\d+)\s*m", s)
    mi = int(m2[0]) if m2 else 0
    s2 = re.findall(r"(\d+)\s*s", s)
    se = int(s2[0]) if s2 else 0
    if h or mi or se:
        return h*3600 + mi*60 + se
    # "01:23:45" / "12:34"
    parts = [p for p in re.split(r"[:]", s) if p.isdigit()]
    try:
        if len(parts) == 3:
            return int(parts[0])*3600 + int(parts[1])*60 + int(parts[2])
        if len(parts) == 2:
            return int(parts[0])*60 + int(parts[1])
    except Exception:
        pass
    return None

def _density_guess(material: str | None) -> float:
    m = (material or "").lower()
    if "petg" in m: return 1.27
    if "abs" in m:  return 1.04
    if "asa" in m:  return 1.07
    if "pc"  in m:  return 1.20
    if "tpu" in m:  return 1.20
    # default PLA
    return 1.24

def _grams_from_mm(length_mm: float, diameter_mm: float, material: str | None) -> float:
    # volume(mm^3) = area * length; area = pi*(d/2)^2; mm^3 -> cm^3: /1000
    area = math.pi * (diameter_mm/2.0)**2  # mm^2
    vol_cm3 = (area * length_mm) / 1000.0
    return vol_cm3 * _density_guess(material)

_PRUSASLICER_CMD: list[str] | None = None


def _is_executable(path: str) -> bool:
    try:
        return os.path.isfile(path) and os.access(path, os.X_OK)
    except Exception:
        return False


def _resolve_prusaslicer_cmd() -> list[str]:
    global _PRUSASLICER_CMD
    if _PRUSASLICER_CMD:
        return list(_PRUSASLICER_CMD)

    env = os.getenv("PRUSASLICER_BIN")
    if env:
        parts = shlex.split(env)
        if parts:
            cmd = parts[0]
            if shutil.which(cmd) or _is_executable(cmd):
                _PRUSASLICER_CMD = parts
                return list(_PRUSASLICER_CMD)

    names = [
        "prusaslicer",
        "PrusaSlicer",
        "PrusaSlicer-console",
        "prusa-slicer",
        "prusa-slicer-console",
        "PrusaSlicer-app",
        "PrusaSlicer.AppImage",
    ]
    static_paths = [
        "/usr/bin/prusaslicer",
        "/usr/bin/PrusaSlicer",
        "/usr/local/bin/prusaslicer",
        "/usr/local/bin/PrusaSlicer",
        "/opt/prusaslicer/prusaslicer",
        "/opt/prusaslicer/PrusaSlicer",
        "/opt/prusaslicer/usr/bin/prusa-slicer",
        "/PrusaSlicer/PrusaSlicer",
        "/PrusaSlicer/prusa-slicer",
        "/app/PrusaSlicer",
        "/app/PrusaSlicer.AppImage",
        "/app/PrusaSlicer/PrusaSlicer",
        "/app/PrusaSlicer/prusa-slicer",
        "/app/PrusaSlicer/bin/prusa-slicer",
        "/app/PrusaSlicer/bin/PrusaSlicer",
    ]
    checked: set[str] = set()

    def _register(result: list[str]) -> list[str]:
        global _PRUSASLICER_CMD
        _PRUSASLICER_CMD = result
        return list(_PRUSASLICER_CMD)

    for cand in names:
        if os.path.basename(cand) == cand:
            resolved = shutil.which(cand)
            if resolved:
                return _register([resolved])

    for cand in static_paths:
        if cand in checked:
            continue
        checked.add(cand)
        if _is_executable(cand):
            return _register([cand])

    search_roots = [
        "/app",
        "/opt",
        "/usr/local",
    ]
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                for filename in filenames:
                    low = filename.lower()
                    if "prusaslicer" not in low:
                        continue
                    path = os.path.join(dirpath, filename)
                    if _is_executable(path):
                        return _register([path])
                # prune deeply nested directories quickly
                dirnames[:] = [d for d in dirnames if "cache" not in d.lower()]
        except Exception:
            continue
    raise FileNotFoundError


def _build_prusaslicer_args(
    base_cmd: list[str],
    input_path: str,
    output_path: str,
    preset_print: str | None,
    preset_filament: str | None,
    preset_printer: str | None,
) -> list[str]:
    args = list(base_cmd) + [
        "--no-gui",
        "--export-gcode",
        "--load",
        "/profiles/print.ini",
        "--load",
        "/profiles/filament.ini",
        "--load",
        "/profiles/printer.ini",
        "--output",
        output_path,
    ]

    preset_args: list[str] = []
    if preset_print:
        preset_args.extend(["--print", preset_print])
    if preset_filament:
        preset_args.extend(["--filament", preset_filament])
    if preset_printer:
        preset_args.extend(["--printer", preset_printer])

    if preset_args:
        args.extend(["--datadir", "/profiles"])
        args.extend(preset_args)

    args.append(input_path)

    return _sanitize_prusaslicer_args(args)


def _sanitize_prusaslicer_args(args: list[str]) -> list[str]:
    """Remove known unsupported flags that may sneak in via configuration."""

    cleaned: list[str] = []
    for item in args:
        if item == "--no-gui":
            continue
        cleaned.append(item)
    return cleaned


def _invoke_prusaslicer(
    input_path: str,
    output_path: str,
    preset_print: str | None,
    preset_filament: str | None,
    preset_printer: str | None,
) -> None:
    try:
        base_cmd = _resolve_prusaslicer_cmd()
    except FileNotFoundError:
        raise HTTPException(500, "PrusaSlicer non trovato nel container.")
    args = _build_prusaslicer_args(
        base_cmd,
        input_path,
        output_path,
        preset_print,
        preset_filament,
        preset_printer,
    )

    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=1200,
        )
    except FileNotFoundError:
        raise HTTPException(500, "PrusaSlicer non trovato nel container.")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "PrusaSlicer ha impiegato troppo tempo.")

    if res.returncode != 0:
        msg = res.stderr or res.stdout or "Errore sconosciuto"
        raise HTTPException(500, f"Errore PrusaSlicer: {msg[:600]}")

def _run_prusaslicer(model_path: str, preset_print: str | None, preset_filament: str | None, preset_printer: str | None) -> str:
    with tempfile.TemporaryDirectory() as td:
        out_path = os.path.join(td, "out.gcode")
        _invoke_prusaslicer(
            model_path,
            out_path,
            preset_print,
            preset_filament,
            preset_printer,
        )

        if not os.path.exists(out_path):
            raise HTTPException(500, "G-code non generato.")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

def _resolve_model_path(viewer_url: str | None) -> str | None:
    if not viewer_url:
        return None
    # la UI passa /ui/uploads/<file>
    m = re.search(r"/ui/uploads/([^/?#]+)", viewer_url)
    if not m:
        return None
    file_name = m.group(1)
    path = os.path.join(WEB_DIR, "uploads", file_name)
    return path if os.path.isfile(path) else None

@app.post("/api/estimate")
async def api_estimate(
    model: UploadFile | None = File(default=None),
    viewer_url: str | None = Form(default=None),
    model_url: str | None = Form(default=None),  # alias
    material: str | None = Form(default=None),
    diameter: str | None = Form(default=None),
    price_per_kg: float | None = Form(default=None),
    hourly_rate: float | None = Form(default=None),
    preset_print: str | None = Form(default=None),
    preset_filament: str | None = Form(default=None),
    preset_printer: str | None = Form(default=None),
):
    # risolvi modello: upload oppure modello già caricato nel viewer
    tmp_path = None
    model_path = None

    if model is not None:
        ext = os.path.splitext(model.filename or "model")[1].lower()
        if ext not in ALLOWED_EXTS:
            raise HTTPException(400, f"Estensione non supportata: {ext}")
        td = tempfile.mkdtemp(prefix="model-")
        tmp_path = os.path.join(td, os.path.basename(model.filename or "model") or "model")  # nosec
        with open(tmp_path, "wb") as f:
            f.write(await model.read())
        model_path = tmp_path
    else:
        model_path = _resolve_model_path(viewer_url) or _resolve_model_path(model_url)
        if not model_path:
            raise HTTPException(400, "Nessun modello fornito. Passa file oppure viewer_url=/ui/uploads/<file>.")

    # esegui slicing per ottenere stima
    gcode = _run_prusaslicer(model_path, preset_print, preset_filament, preset_printer)

    # parse G-code
    filament_g = None
    filament_mm = None
    time_s = None

    mg = _FIL_G_PAT.search(gcode)
    if mg:
        try:
            filament_g = float(mg.group(1))
        except Exception:
            filament_g = None

    mm = _FIL_MM_PAT.search(gcode)
    if mm:
        try:
            filament_mm = float(mm.group(1))
        except Exception:
            filament_mm = None

    mt = _TIME_PAT.search(gcode)
    if mt:
        time_s = _parse_time_to_seconds(mt.group(1))

    # se mancano i grammi ma abbiamo la lunghezza -> converto io
    if filament_g is None and filament_mm is not None:
        try:
            diam = float(str(diameter or "1.75").replace(",", "."))
        except Exception:
            diam = 1.75
        filament_g = _grams_from_mm(filament_mm, diam, material)

    # costi
    rate = hourly_rate if hourly_rate is not None else HOURLY_RATE
    mat_cost = None
    if price_per_kg is not None and filament_g is not None:
        mat_cost = price_per_kg * (filament_g / 1000.0)

    mach_cost = None
    if rate is not None and time_s is not None:
        mach_cost = rate * (time_s / 3600.0)

    total_cost = None
    if mat_cost is not None and mach_cost is not None:
        total_cost = mat_cost + mach_cost

    # cleanup tmp
    if tmp_path:
        try:
            os.remove(tmp_path)
            os.rmdir(os.path.dirname(tmp_path))
        except Exception:
            pass

    return _no_cache({
        "filament_g": filament_g,
        "filament_mm": filament_mm,
        "time_s": time_s,
        "price_per_kg": price_per_kg,
        "hourly_rate": rate,
        "cost_material": mat_cost,
        "cost_machine": mach_cost,
        "cost_total": total_cost,
        "currency": CURRENCY,
    })

# ---------- Slice (esporta gcode) ----------
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
        _invoke_prusaslicer(
            in_path,
            out_path,
            preset_print,
            preset_filament,
            preset_printer,
        )

        if not os.path.exists(out_path):
            raise HTTPException(500, "G-code non generato.")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            gcode = f.read()

        return PlainTextResponse(gcode)
