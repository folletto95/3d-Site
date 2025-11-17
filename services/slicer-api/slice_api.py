from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Body
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os, tempfile, subprocess, re, colorsys, json, threading, uuid, math, shutil, shlex, logging
from pathlib import Path
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


def _guess_profiles_dir() -> Path:
    candidates: list[Path] = []
    env = os.getenv("PROFILES_DIR")
    if env:
        candidates.append(Path(env))
    candidates.append(Path("/profiles"))
    here = Path(__file__).resolve()
    candidates.append(here.parent.parent.parent / "profiles")
    for candidate in candidates:
        try:
            if candidate.is_dir():
                return candidate.resolve()
        except Exception:
            continue
    return candidates[-1].resolve()


PROFILES_DIR = _guess_profiles_dir()
_BUNDLED_PROFILES_DIR = Path(__file__).resolve().parent.parent.parent / "profiles"


def _existing_dir(*candidates: Path) -> Path:
    for candidate in candidates:
        try:
            if candidate and candidate.is_dir():
                return candidate.resolve()
        except Exception:
            continue
    return candidates[-1].resolve()


def _existing_profile(*candidates: Path) -> Path:
    for candidate in candidates:
        try:
            if candidate and candidate.is_file():
                return candidate.resolve()
        except Exception:
            continue
    return candidates[-1].resolve()


PRINT_PRESETS_DIR = _existing_dir(PROFILES_DIR / "print", _BUNDLED_PROFILES_DIR / "print")
DEFAULT_PRINT_PROFILE = _existing_profile(
    PROFILES_DIR / "print.ini",
    _BUNDLED_PROFILES_DIR / "print.ini",
)
DEFAULT_FILAMENT_PROFILE = _existing_profile(
    PROFILES_DIR / "filament.ini",
    _BUNDLED_PROFILES_DIR / "filament.ini",
)
DEFAULT_PRINTER_PROFILE = _existing_profile(
    PROFILES_DIR / "printer.ini",
    _BUNDLED_PROFILES_DIR / "printer.ini",
)

_PRINT_PRESET_FILES = {
    "standard": "x1c_standard_020.ini",
    "0.20 standard": "x1c_standard_020.ini",
    "0.20mm standard": "x1c_standard_020.ini",
    "x1c_standard_020": "x1c_standard_020.ini",
    "x1c_standard_020.ini": "x1c_standard_020.ini",
    "quality": "x1c_quality_016.ini",
    "0.16 quality": "x1c_quality_016.ini",
    "0.16mm quality": "x1c_quality_016.ini",
    "0.16 quality mode": "x1c_quality_016.ini",
    "x1c_quality_016": "x1c_quality_016.ini",
    "x1c_quality_016.ini": "x1c_quality_016.ini",
    "fine": "x1c_fine_012.ini",
    "0.12 fine": "x1c_fine_012.ini",
    "0.12mm fine": "x1c_fine_012.ini",
    "x1c_fine_012": "x1c_fine_012.ini",
    "x1c_fine_012.ini": "x1c_fine_012.ini",
    "draft": "x1c_draft_028.ini",
    "0.28 draft": "x1c_draft_028.ini",
    "0.28mm draft": "x1c_draft_028.ini",
    "x1c_draft_028": "x1c_draft_028.ini",
    "x1c_draft_028.ini": "x1c_draft_028.ini",
    "strength": "x1c_strength_020.ini",
    "0.20 strength": "x1c_strength_020.ini",
    "x1c_strength_020": "x1c_strength_020.ini",
    "x1c_strength_020.ini": "x1c_strength_020.ini",
    "lightning": "x1c_lightning_020.ini",
    "0.20 lightning": "x1c_lightning_020.ini",
    "x1c_lightning_020": "x1c_lightning_020.ini",
    "x1c_lightning_020.ini": "x1c_lightning_020.ini",
    "ultrafine": "x1c_ultrafine_008.ini",
    "0.08 ultra fine": "x1c_ultrafine_008.ini",
    "0.08 ultrafine": "x1c_ultrafine_008.ini",
    "x1c_ultrafine_008": "x1c_ultrafine_008.ini",
    "x1c_ultrafine_008.ini": "x1c_ultrafine_008.ini",
}


def _normalize_preset_key(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())

_LOG = logging.getLogger("slicer.prusaslicer")
_LOG.addHandler(logging.NullHandler())

_HEX_RE = re.compile(r"#?[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_PRINT_SETTINGS_ID_RE = re.compile(r";\s*print_settings_id\s*=\s*(.+)")
_FILAMENT_SETTINGS_ID_RE = re.compile(r";\s*filament_settings_id\s*=\s*(.+)")
_PRINTER_SETTINGS_ID_RE = re.compile(r";\s*printer_settings_id\s*=\s*(.+)")

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


def _hex_norm(value: str | None) -> str:
    if not value:
        return "#777777"
    text = str(value).strip()
    if not text.startswith("#"):
        text = f"#{text}"
    return text.upper()


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


def _profile_alias(kind: str, preset: str) -> str:
    if kind != "print":
        return preset
    key = _normalize_preset_key(str(preset))
    mapped = _PRINT_PRESET_FILES.get(key)
    if mapped:
        return mapped
    return preset


def _profile_search_dirs(kind: str) -> list[Path]:
    primary = PRINT_PRESETS_DIR if kind == "print" else PROFILES_DIR / kind
    bundled = (
        _BUNDLED_PROFILES_DIR / "print"
        if kind == "print"
        else _BUNDLED_PROFILES_DIR / kind
    )
    bases = [primary, bundled, PROFILES_DIR, _BUNDLED_PROFILES_DIR]
    dirs: list[Path] = []
    for base in bases:
        try:
            if base and base.is_dir():
                resolved = base.resolve()
                if resolved not in dirs:
                    dirs.append(resolved)
        except Exception:
            continue
    return dirs


def _profile_candidates(kind: str, preset: str) -> list[Path]:
    preset = _profile_alias(kind, preset)
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", preset.strip())
    candidates: list[Path] = []
    files_to_try: list[str] = []
    if cleaned.lower().endswith(".ini"):
        files_to_try.append(cleaned)
    else:
        files_to_try.append(f"{cleaned}.ini")
        files_to_try.append(cleaned)
    for name in files_to_try:
        if not name:
            continue
        if "/" in name or "\\" in name or name.startswith(".."):
            continue
        for directory in _profile_search_dirs(kind):
            candidates.append(directory / name)
    return candidates


def _resolve_profile_path(kind: str, preset: str | None) -> tuple[Path, bool]:
    if not preset or not str(preset).strip():
        raise HTTPException(400, f"preset_{kind} mancante: passalo dal frontend")

    text = str(preset).strip()
    for candidate in _profile_candidates(kind, text):
        try:
            if candidate.is_file():
                return candidate.resolve(), True
        except Exception:
            continue

    raise HTTPException(400, f"Profilo {kind} '{text}' non trovato nel container")


def _slug(value: str | None) -> str:
    if not value:
        return ""
    text = str(value).lower()
    slug = _SLUG_RE.sub("-", text).strip("-")
    return slug[:64]


def _build_gcode_output_path(
    temp_dir: str,
    model_path: str,
    preset_print: str | None,
    preset_filament: str | None,
    preset_printer: str | None,
) -> str:
    base_name = Path(model_path).stem or "model"
    base_slug = _slug(base_name) or "model"
    suffix_parts = [
        part for part in (
            _slug(preset_print),
            _slug(preset_filament),
            _slug(preset_printer),
        )
        if part
    ]
    suffix = "-".join(suffix_parts) if suffix_parts else "default"
    filename = f"{base_slug}-{suffix}.gcode"
    path = (Path(temp_dir) / filename).resolve()
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass
    return str(path)

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
async def _fetch_inventory_items() -> list[dict]:
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
    return out


def _inventory_key_for_index(item: dict, index: int) -> str:
    raw_key = item.get("key")
    if raw_key not in (None, ""):
        return str(raw_key)
    color = _hex_norm(item.get("color_hex") or item.get("hex") or "#777777")
    material = str(item.get("material") or "mat")
    return f"{material}_{color}_{index}"


async def _resolve_inventory_context(key: str | None) -> dict:
    if not key:
        return {}
    try:
        items = await _fetch_inventory_items()
    except HTTPException:
        raise
    except Exception:
        return {}
    for idx, item in enumerate(items):
        if _inventory_key_for_index(item, idx) == key:
            return item
    return {}


def _normalize_viewer_url(url: str | None) -> str | None:
    if not url:
        return None
    text = str(url).strip()
    if not text:
        return None
    if text.startswith("/ui/uploads/"):
        return text
    if text.startswith("/files/"):
        name = text.split("/")[-1].split("?")[0]
        if name:
            return f"/ui/uploads/{name}"
    return text


def _to_float(value, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(str(value).replace(",", "."))
    except Exception:
        return default


@app.get("/inventory")
async def inventory():
    items = await _fetch_inventory_items()
    return _no_cache({"items": items, "hourly_rate": HOURLY_RATE, "currency": CURRENCY})

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
_FIL_USAGE_PATTERNS = [
    re.compile(r";\s*filament\s+used\s*\[\s*([^\]]+)\s*\]\s*[=:]\s*([\d.,eE+-]+)", re.I),
    re.compile(r";\s*total\s+filament\s+used\s*\[\s*([^\]]+)\s*\]\s*[=:]\s*([\d.,eE+-]+)", re.I),
    re.compile(r";\s*material\s+used\s*\[\s*([^\]]+)\s*\]\s*[=:]\s*([\d.,eE+-]+)", re.I),
]
_FIL_USAGE_SIMPLE_PATTERNS = [
    re.compile(r";\s*estimated\s+filament\s+usage\s*[:=]\s*([\d.,eE+-]+)\s*([a-zA-Z0-9^]+)?", re.I),
    re.compile(r";\s*total\s+filament\s*[:=]\s*([\d.,eE+-]+)\s*([a-zA-Z0-9^]+)?", re.I),
]

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

def _grams_from_volume_mm3(volume_mm3: float, material: str | None) -> float:
    return (volume_mm3 / 1000.0) * _density_guess(material)


def _parse_decimal(value: str) -> float | None:
    try:
        return float(value.replace(",", "."))
    except Exception:
        return None


def _parse_filament_usage_from_comments(gcode: str) -> tuple[float | None, float | None, float | None]:
    total_g = 0.0
    total_len_mm = 0.0
    total_vol_mm3 = 0.0

    for pattern in _FIL_USAGE_PATTERNS:
        for match in pattern.finditer(gcode):
            unit = (match.group(1) or "").strip().lower().replace(" ", "")
            value = _parse_decimal(match.group(2) or "")
            if value is None:
                continue
            if unit in {"g", "gram", "grams"}:
                total_g += value
            elif unit in {"kg"}:
                total_g += value * 1000.0
            elif unit in {"mm"}:
                total_len_mm += value
            elif unit in {"m"}:
                total_len_mm += value * 1000.0
            elif unit in {"cm3", "cm^3"}:
                total_vol_mm3 += value * 1000.0
            elif unit in {"mm3", "mm^3"}:
                total_vol_mm3 += value

    for pattern in _FIL_USAGE_SIMPLE_PATTERNS:
        for match in pattern.finditer(gcode):
            value = _parse_decimal(match.group(1) or "")
            if value is None:
                continue
            unit = (match.group(2) or "").strip().lower().replace(" ", "")
            if not unit:
                total_g += value
                continue
            if unit in {"g", "gram", "grams"}:
                total_g += value
            elif unit in {"kg"}:
                total_g += value * 1000.0
            elif unit in {"mm"}:
                total_len_mm += value
            elif unit in {"m"}:
                total_len_mm += value * 1000.0
            elif unit in {"cm3", "cm^3"}:
                total_vol_mm3 += value * 1000.0
            elif unit in {"mm3", "mm^3"}:
                total_vol_mm3 += value

    grams = total_g if total_g > 0 else None
    length = total_len_mm if total_len_mm > 0 else None
    volume = total_vol_mm3 if total_vol_mm3 > 0 else None
    return grams, length, volume


def _estimate_filament_length_from_gcode_text(gcode: str) -> float:
    totals: dict[int, float] = {}
    last_e: dict[int, float | None] = {}
    current_tool = 0
    relative_mode = False

    totals.setdefault(current_tool, 0.0)
    last_e.setdefault(current_tool, None)

    for raw_line in gcode.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if ";" in line:
            line = line.split(";", 1)[0].strip()
            if not line:
                continue

        upper = line.upper()

        if upper.startswith("T") and len(line) > 1 and line[1].isdigit():
            try:
                current_tool = int(re.match(r"T(\d+)", line).group(1))
            except Exception:
                current_tool = 0
            totals.setdefault(current_tool, 0.0)
            last_e.setdefault(current_tool, None)
            continue

        if "M82" in upper:
            relative_mode = False
            last_e[current_tool] = None
            continue
        if "M83" in upper:
            relative_mode = True
            last_e[current_tool] = None
            continue

        if ("G92" in upper or "M92" in upper) and "E" in upper:
            last_e[current_tool] = 0.0 if not relative_mode else None
            continue

        match = re.search(r"\bE([+-]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[eE][+-]?\d+)?)", line)
        if not match:
            continue

        value = _parse_decimal(match.group(1))
        if value is None:
            continue

        if relative_mode:
            diff = value
        else:
            prev = last_e.get(current_tool)
            if prev is None:
                last_e[current_tool] = value
                continue
            diff = value - prev
            last_e[current_tool] = value

        if diff <= 0 or diff > 1000:
            continue

        totals[current_tool] = totals.get(current_tool, 0.0) + diff

    return sum(totals.values())


def _parse_preset_ids_from_gcode(gcode: str) -> dict[str, str | None]:
    def _match(pattern: re.Pattern[str]) -> str | None:
        m = pattern.search(gcode)
        if not m:
            return None
        value = (m.group(1) or "").strip()
        if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
            value = value[1:-1].strip()
        return value or None

    return {
        "print": _match(_PRINT_SETTINGS_ID_RE),
        "filament": _match(_FILAMENT_SETTINGS_ID_RE),
        "printer": _match(_PRINTER_SETTINGS_ID_RE),
    }


def _extract_settings_id_from_profile(path: Path, key: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith(";") or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                lhs, rhs = line.split("=", 1)
                if lhs.strip().lower() != key.strip().lower():
                    continue
                value = rhs.strip()
                if value.startswith(('"', "'")) and value.endswith(('"', "'")) and len(value) >= 2:
                    value = value[1:-1].strip()
                return value or None
    except Exception:
        return None
    return None


def _profile_cli_name(kind: str, path: Path) -> str | None:
    key_order = {
        "print": ["print_profile", "print_settings_id", "name"],
        "filament": ["filament_profile", "name", "filament_settings_id"],
        "printer": ["printer_profile", "name", "printer_settings_id"],
    }
    tried: set[str] = set()
    for key in key_order.get(kind, []):
        if key in tried:
            continue
        tried.add(key)
        value = _extract_settings_id_from_profile(path, key)
        if value:
            return value
    if "name" not in tried:
        value = _extract_settings_id_from_profile(path, "name")
        if value:
            return value
    return None


def _normalize_settings_id(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


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


def _clean_requested_preset(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _resolve_profiles(
    preset_print: str | None,
    preset_filament: str | None,
    preset_printer: str | None,
) -> dict[str, dict[str, object]]:
    profiles = {
        "print": {},
        "filament": {},
        "printer": {},
    }

    printer_profile, printer_found = _resolve_profile_path("printer", preset_printer)
    filament_profile, filament_found = _resolve_profile_path("filament", preset_filament)
    print_profile, print_found = _resolve_profile_path("print", preset_print)

    profiles["printer"] = {
        "requested": _clean_requested_preset(preset_printer),
        "path": printer_profile,
        "found": printer_found,
    }
    profiles["filament"] = {
        "requested": _clean_requested_preset(preset_filament),
        "path": filament_profile,
        "found": filament_found,
    }
    profiles["print"] = {
        "requested": _clean_requested_preset(preset_print),
        "path": print_profile,
        "found": print_found,
    }

    return profiles


def _build_prusaslicer_args(
    base_cmd: list[str],
    input_path: str,
    output_path: str,
    profiles: dict[str, dict[str, object]],
    *,
    override_settings: dict | None = None,
    set_args: list[str] | None = None,
) -> list[str]:
    printer_profile = profiles["printer"]["path"]
    filament_profile = profiles["filament"]["path"]
    print_profile = profiles["print"]["path"]

    if set_args is None:
        set_args, _ = _build_override_set_args(override_settings)

    args = list(base_cmd) + [
        "--export-gcode",
        "--load",
        str(printer_profile),
        "--load",
        str(filament_profile),
        "--load",
        str(print_profile),
        "--output",
        output_path,
    ]

    if set_args:
        args.extend(set_args)

    args.append(input_path)

    return _sanitize_prusaslicer_args(args)


def _sanitize_prusaslicer_args(args: list[str]) -> list[str]:
    """Remove known unsupported flags that may sneak in via configuration."""

    cleaned: list[str] = []
    for item in args:
        if item in {"--no-gui", "--nogui"}:
            # Some builds do not recognize the GUI toggle; drop it to avoid failures.
            continue
        cleaned.append(item)
    return cleaned


def _praslicer_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    return env


def _fmt_set_value(value: float) -> str:
    text = f"{value:.4f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _build_override_set_args(settings: dict | None) -> tuple[list[str], dict[str, float]]:
    if not settings:
        return [], {}

    applied: dict[str, float] = {}
    args: list[str] = []

    def _add(config_keys: list[str], src_key: str):
        raw = settings.get(src_key)
        val = _to_float(raw, None)
        if val is None:
            return
        for key in config_keys:
            applied[key] = val
            args.extend(["--set", f"{key}={_fmt_set_value(val)}"])

    _add(["layer_height"], "layer_h")
    _add(["infill_density"], "infill")
    _add(["nozzle_diameter"], "nozzle")
    _add(["travel_speed"], "travel_speed")
    _add(
        [
            "perimeter_speed",
            "external_perimeter_speed",
            "infill_speed",
            "solid_infill_speed",
            "top_solid_infill_speed",
        ],
        "print_speed",
    )

    return args, applied


def _invoke_prusaslicer(
    input_path: str,
    output_path: str,
    profiles: dict[str, dict[str, object]],
    *,
    override_settings: dict | None = None,
) -> tuple[list[str], dict[str, float]]:
    set_args, applied_overrides = _build_override_set_args(override_settings)
    try:
        base_cmd = _resolve_prusaslicer_cmd()
    except FileNotFoundError:
        raise HTTPException(500, "PrusaSlicer non trovato nel container.")
    args = _build_prusaslicer_args(
        base_cmd,
        input_path,
        output_path,
        profiles,
        override_settings=override_settings,
        set_args=set_args,
    )

    try:
        rendered_cmd = shlex.join(args)
    except Exception:
        rendered_cmd = " ".join(args)
    _LOG.info("PrusaSlicer cmd: %s", rendered_cmd)

    try:
        res = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=1200,
            env=_praslicer_env(),
        )
    except FileNotFoundError:
        raise HTTPException(500, "PrusaSlicer non trovato nel container.")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "PrusaSlicer ha impiegato troppo tempo.")

    if res.returncode != 0:
        msg = res.stderr or res.stdout or "Errore sconosciuto"
        raise HTTPException(500, f"Errore PrusaSlicer: {msg[:600]}")

    return args, applied_overrides

def _run_prusaslicer(
    model_path: str,
    profiles: dict[str, dict[str, object]],
    *,
    override_settings: dict | None = None,
) -> tuple[str, list[str], dict[str, float]]:
    with tempfile.TemporaryDirectory() as td:
        out_path = _build_gcode_output_path(
            td,
            model_path,
            profiles["print"].get("requested"),
            profiles["filament"].get("requested"),
            profiles["printer"].get("requested"),
        )
        executed_cmd, applied_overrides = _invoke_prusaslicer(
            model_path,
            out_path,
            profiles,
            override_settings=override_settings,
        )

        if not os.path.exists(out_path):
            raise HTTPException(500, "G-code non generato.")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read(), executed_cmd, applied_overrides

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


def _estimate_print_job(
    model_path: str,
    profiles: dict[str, dict[str, object]],
    *,
    material: str | None,
    diameter: str | float | None,
    price_per_kg: float | None,
    rate: float | None,
    override_settings: dict | None = None,
) -> dict:
    gcode, prusaslicer_cmd, applied_overrides = _run_prusaslicer(
        model_path,
        profiles,
        override_settings=override_settings,
    )

    preset_ids = _parse_preset_ids_from_gcode(gcode)
    filament_g = None
    filament_mm = None
    time_s = None

    grams_comment, mm_comment, vol_comment = _parse_filament_usage_from_comments(gcode)
    if grams_comment is not None:
        filament_g = grams_comment
    if mm_comment is not None:
        filament_mm = mm_comment
    if filament_g is None and vol_comment is not None:
        filament_g = _grams_from_volume_mm3(vol_comment, material)

    mt = _TIME_PAT.search(gcode)
    if mt:
        time_s = _parse_time_to_seconds(mt.group(1))

    if filament_g is None and filament_mm is not None:
        diam_val = _to_float(diameter, 1.75) or 1.75
        filament_g = _grams_from_mm(filament_mm, diam_val, material)

    if filament_mm is None or filament_g is None:
        fallback_mm = _estimate_filament_length_from_gcode_text(gcode)
        if fallback_mm > 0 and filament_mm is None:
            filament_mm = fallback_mm
        if filament_g is None and filament_mm is not None:
            diam_val = _to_float(diameter, 1.75) or 1.75
            filament_g = _grams_from_mm(filament_mm, diam_val, material)

    eff_rate = rate if rate is not None else HOURLY_RATE
    mat_cost = None
    if price_per_kg is not None and filament_g is not None:
        mat_cost = price_per_kg * (filament_g / 1000.0)

    mach_cost = None
    if eff_rate is not None and time_s is not None:
        mach_cost = eff_rate * (time_s / 3600.0)

    total_cost = None
    if mat_cost is not None and mach_cost is not None:
        total_cost = mat_cost + mach_cost

    def _profile_summary(kind: str) -> dict[str, object]:
        info = profiles[kind]
        path = info["path"]
        filename = ""
        try:
            filename = Path(path).name
        except Exception:
            filename = str(path)

        reported_id = preset_ids.get(kind)
        if reported_id and isinstance(reported_id, str):
            reported_id = reported_id.strip()

        settings_key_map = {
            "print": "print_settings_id",
            "filament": "filament_settings_id",
            "printer": "printer_settings_id",
        }
        expected_id = None
        settings_key = settings_key_map.get(kind)
        if settings_key:
            expected_id = _extract_settings_id_from_profile(path, settings_key)

        normalized_reported = _normalize_settings_id(reported_id)
        normalized_expected = _normalize_settings_id(expected_id)
        matches_expected = bool(normalized_reported and normalized_expected and normalized_reported == normalized_expected)

        return {
            "requested": info.get("requested"),
            "path": str(path),
            "filename": filename,
            "found": bool(info.get("found")),
            "is_default": not bool(info.get("found")),
            "reported_id": reported_id,
            "expected_id": expected_id,
            "reported_matches_expected": matches_expected,
        }

    presets_used = {
        "print": _profile_summary("print"),
        "filament": _profile_summary("filament"),
        "printer": _profile_summary("printer"),
    }

    if (
        presets_used["print"].get("reported_id")
        and presets_used["print"].get("expected_id")
        and not presets_used["print"].get("reported_matches_expected")
    ):
        _LOG.warning(
            "Preset stampa richiesto '%s' (file %s) ma G-code riporta print_settings_id '%s'",
            presets_used["print"].get("requested"),
            presets_used["print"].get("filename"),
            presets_used["print"].get("reported_id"),
        )

    return {
        "gcode": gcode,
        "filament_g": filament_g,
        "filament_mm": filament_mm,
        "time_s": time_s,
        "price_per_kg": price_per_kg,
        "hourly_rate": eff_rate,
        "cost_material": mat_cost,
        "cost_machine": mach_cost,
        "cost_total": total_cost,
        "currency": CURRENCY,
        "preset_print_used": presets_used["print"]["filename"],
        "preset_printer_used": presets_used["printer"]["filename"],
        "preset_filament_used": presets_used["filament"]["filename"],
        "preset_print_is_default": presets_used["print"]["is_default"],
        "preset_print_reported_id": presets_used["print"].get("reported_id"),
        "preset_print_expected_id": presets_used["print"].get("expected_id"),
        "preset_print_matches": presets_used["print"].get("reported_matches_expected"),
        "preset_printer_reported_id": presets_used["printer"].get("reported_id"),
        "preset_filament_reported_id": presets_used["filament"].get("reported_id"),
        "presets_used": presets_used,
        "prusaslicer_cmd": prusaslicer_cmd,
        "override_settings": applied_overrides or None,
    }

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

    profiles = _resolve_profiles(preset_print, preset_filament, preset_printer)

    try:
        result = _estimate_print_job(
            model_path,
            profiles,
            material=material,
            diameter=diameter,
            price_per_kg=price_per_kg,
            rate=hourly_rate,
            override_settings=None,
        )
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
                os.rmdir(os.path.dirname(tmp_path))
            except Exception:
                pass

    payload = dict(result)
    payload.pop("gcode", None)
    return _no_cache(payload)


async def _modern_estimate(payload: dict) -> JSONResponse:
    if not isinstance(payload, dict):
        raise HTTPException(400, "Payload JSON non valido")

    viewer_url = _normalize_viewer_url(payload.get("viewer_url"))
    model_path = _resolve_model_path(viewer_url)
    if not model_path:
        raise HTTPException(400, "viewer_url non valido o file inesistente")

    inventory_key = payload.get("inventory_key")
    inventory_context = await _resolve_inventory_context(str(inventory_key)) if inventory_key else {}

    material = payload.get("material") or inventory_context.get("material")
    diameter = payload.get("diameter") or inventory_context.get("diameter")

    price_per_kg = payload.get("price_per_kg")
    if price_per_kg is None:
        price_per_kg = inventory_context.get("price_per_kg")
    price_per_kg = _to_float(price_per_kg, None)

    hourly_rate = payload.get("hourly_rate")
    hourly_rate = _to_float(hourly_rate, None)

    preset_print = payload.get("preset_print")
    preset_filament = payload.get("preset_filament")
    preset_printer = payload.get("preset_printer")

    settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
    if not preset_print and settings:
        preset_print = settings.get("profile") or settings.get("preset_print")
    if not preset_printer and settings:
        preset_printer = settings.get("printer_profile") or settings.get("preset_printer")

    profiles = _resolve_profiles(preset_print, preset_filament, preset_printer)
    result = _estimate_print_job(
        model_path,
        profiles,
        material=material,
        diameter=diameter,
        price_per_kg=price_per_kg,
        rate=hourly_rate,
        override_settings=settings,
    )

    response = dict(result)
    response.pop("gcode", None)

    debug_payload: dict[str, object] = {}
    prusa_debug: dict[str, object] = {}
    if result.get("prusaslicer_cmd"):
        prusa_debug["prusaslicer_cmd"] = result.get("prusaslicer_cmd")
    if result.get("override_settings"):
        prusa_debug["prusaslicer_overrides"] = result.get("override_settings")
    if result.get("presets_used"):
        prusa_debug["presets_used"] = result.get("presets_used")

    if prusa_debug:
        debug_payload.update(prusa_debug)
    if settings:
        debug_payload["settings"] = settings
    if inventory_context:
        debug_payload["inventory"] = inventory_context
    if debug_payload:
        response["debug"] = debug_payload

    return _no_cache(response)


@app.post("/slice/estimate")
async def modern_slice_estimate(payload: dict = Body(...)):
    return await _modern_estimate(payload)


@app.post("/api/slice/estimate")
async def modern_slice_estimate_prefixed(payload: dict = Body(...)):
    return await _modern_estimate(payload)


@app.get("/slice/estimate")
@app.get("/api/slice/estimate")
async def modern_slice_estimate_info():
    return _no_cache(
        {
            "detail": "Invia un JSON a POST /slice/estimate per ottenere la stima.",
            "method": "POST",
            "payload": {
                "viewer_url": "/ui/uploads/<file>",
                "inventory_key": "<chiave_materiale>",
                "preset_print": "<profilo_stampa>.ini",
                "preset_printer": "<profilo_stampante>.ini",
            },
            "note": "Il campo 'settings' è opzionale e va inviato solo per override manuali.",
        }
    )

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
        profiles = _resolve_profiles(preset_print, preset_filament, preset_printer)
        _invoke_prusaslicer(
            in_path,
            out_path,
            profiles,
            override_settings=None,
        )

        if not os.path.exists(out_path):
            raise HTTPException(500, "G-code non generato.")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            gcode = f.read()

        return PlainTextResponse(gcode)
