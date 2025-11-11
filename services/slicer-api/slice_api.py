from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os, tempfile, subprocess, re, colorsys, json, threading
import httpx

app = FastAPI(title="slicer-api", version="0.8.1")

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

SPOOLMAN_BASE = os.getenv("SPOOLMAN_BASE") or os.getenv("SPOOLMAN_URL") or ""
SPOOLMAN_PATHS = os.getenv("SPOOLMAN_PATHS") or "/api/v1/spool/?page_size=1000,/api/v1/spools?page_size=1000,/api/spool/?page_size=1000,/api/spools?page_size=1000"
CURRENCY = os.getenv("CURRENCY", "EUR")
HOURLY_RATE = _env_float("HOURLY_RATE", 1.0)

def _bases_from_env():
    bases = []
    if SPOOLMAN_BASE:
        bases.append(SPOOLMAN_BASE.rstrip("/"))
    for raw in os.getenv("SPOOLMAN_BASES", "").split(","):
        raw = raw.strip()
        if raw:
            bases.append(raw.rstrip("/"))
    if not bases:
        bases.append("http://spoolman:7912")
    return list(dict.fromkeys(bases))  # unique

def _paths_from_env():
    paths = []
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

# --- Mappa dei colori personalizzabile (colors.json) ---
def _guess_colors_json_path() -> str:
    """Prova a trovare web/colors.json in modo robusto.

    Ordine di ricerca:
    1. Variabile d'ambiente COLORS_JSON_PATH (se esiste).
    2. CWD/web/colors.json (dove parte il processo uvicorn).
    3. ../../web/colors.json relativo a questo file.
    4. Per alcuni livelli verso l'alto: <dir>/web/colors.json.
    """
    env = os.getenv("COLORS_JSON_PATH")
    candidates: list[str] = []
    if env:
        candidates.append(env)

    # CWD
    try:
        cwd = os.getcwd()
        candidates.append(os.path.join(cwd, "web", "colors.json"))
    except Exception:
        pass

    # ../../web/colors.json relativo a questo file
    here = os.path.dirname(__file__)
    candidates.append(os.path.join(here, "..", "..", "web", "colors.json"))

    # sali qualche livello e cerca web/colors.json
    base = here
    for _ in range(4):
        base = os.path.dirname(base)
        if not base or base == os.path.sep:
            break
        candidates.append(os.path.join(base, "web", "colors.json"))

    # normalizza, scegli il primo che esiste
    norm: list[str] = []
    for c in candidates:
        if not c:
            continue
        p = os.path.abspath(c)
        if p not in norm:
            norm.append(p)
    for p in norm:
        if os.path.isfile(p):
            return p
    # fallback: primo candidato normalizzato, anche se non esiste (verrà creato)
    return norm[0] if norm else os.path.abspath("web/colors.json")


_COLORS_JSON_PATH = _guess_colors_json_path()
_COLORS_LOCK = threading.Lock()
_COLORS_MAP = None  # type: ignore[assignment]
_COLORS_DIRTY = False

def _load_colors_map() -> dict:
    """Carica colors.json come mappa HEX -> nome (chiavi normalizzate)."""
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
                if not hk:
                    continue
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
    """Se vede un HEX nuovo, lo aggiunge a colors.json (con nome iniziale opzionale).
    Poi potrai cambiare il nome a mano nel file."""
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
    """Scrive colors.json solo se sono apparsi nuovi HEX."""
    global _COLORS_DIRTY, _COLORS_MAP
    if not _COLORS_DIRTY or _COLORS_MAP is None:
        return
    with _COLORS_LOCK:
        try:
            tmp = _COLORS_JSON_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(_COLORS_MAP, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(tmp, _COLORS_JSON_PATH)
            _COLORS_DIRTY = False
        except Exception:
            # se fallisce non blocca l'API: al massimo non aggiorna il file
            pass

def _hex_to_name(h: str) -> str:
    """Heuristica IT aggiornata: evita over-classifiche Arancione,
    riconosce rosa pastello, confine Blu/Viola anticipato."""
    h = _normalize_hex(h)
    if not h:
        return "Grigio"
    try:
        r = int(h[1:3], 16) / 255.0
        g = int(h[3:5], 16) / 255.0
        b = int(h[5:7], 16) / 255.0
    except Exception:
        return "Grigio"

    # casi netti
    if r > 0.94 and g > 0.94 and b > 0.94:
        return "Bianco"
    if r < 0.06 and g < 0.06 and b < 0.06:
        return "Nero"

    h_, l, s = colorsys.rgb_to_hls(r, g, b)   # H in [0,1), L,S in [0,1]
    deg = (h_ * 360.0) % 360.0

    # poco saturi -> scala grigi
    if s < 0.10:
        if l > 0.90:
            return "Bianco"
        if l < 0.10:
            return "Nero"
        return "Grigio"

    # rosa pastello (chiaro, poco sat., dominante R)
    if s < 0.35 and l > 0.75 and (deg < 25 or deg > 320):
        return "Rosa"

    # marrone (arancio scuro / poco luminoso)
    if 15 <= deg < 40 and l < 0.55:
        return "Marrone"

    # oro dedicato (giallo caldo saturo)
    if 40 <= deg < 55 and s > 0.40 and l > 0.45:
        return "Oro"

    # fasce principali (leggermente ritoccate)
    if deg < 12 or deg >= 348:
        return "Rosso"
    if 12 <= deg < 40:
        return "Arancione"
    if 55 <= deg < 75:
        return "Giallo"
    if 75 <= deg < 165:
        return "Verde"
    if 165 <= deg < 190:
        return "Ciano"
    if 190 <= deg < 250:
        return "Blu"
    if 250 <= deg < 300:
        return "Viola"
    if 300 <= deg < 350:
        return "Rosa"
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
    if "petg" in mat and "transluc" in blob.lower():  # PETG Translucent
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
    v = spool.get("price_per_kg") or filament.get("price_per_kg")
    if v is None:
        v = spool.get("price_kg") or filament.get("price_kg")
    if v is None:
        return None
    try:
        v = float(v)
    except Exception:
        return None
    if v <= 0:
        return None
    return v

# ---------- Inventory ----------
@app.get("/inventory")
async def inventory():
    verify = not (os.getenv("SPOOLMAN_SKIP_TLS_VERIFY", "").lower() in ("1", "true", "yes"))
    token = os.getenv("SPOOLMAN_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    attempted, data, last_err = [], None, None
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
        raise HTTPException(502, f"Spoolman non raggiungibile. Tentativi: {attempted}  Errore: {last_err}")

    spools = data.get("results") or data.get("spools") if isinstance(data, dict) else data
    spools = spools or []

    items = []
    for s in spools:
        f = _extract_filament_from_spool(s)
        color_hex = _normalize_hex(_first(s, ["color_hex"]) or f.get("color_hex")) or "#777777"
        material = f.get("material") or s.get("material") or "N/A"
        diameter = str(f.get("diameter") or s.get("diameter") or "")
        is_trans = _detect_transparent(s, f, color_hex)

        # 1) prova sempre dal file colors.json (override totale, tranne trasparenti)
        color_name = None
        if not is_trans:
            color_name = _get_color_from_map(color_hex)

        # 2) se non definito lì, usa il nome di Spoolman / filamento
        if not color_name:
            color_name = _first(s, ["color_name", "colour_name"]) or f.get("color_name") or f.get("colour_name")

        # 3) forza "Trasparente" se rilevato come tale
        if is_trans:
            color_name = "Trasparente"

        # 4) fallback heuristico solo se ancora vuoto
        if not color_name:
            color_name = _hex_to_name(color_hex)

        # 5) assicura che ci sia sempre una stringa
        if not color_name:
            color_name = "N/D"

        price_per_kg = _price_per_kg_from_spool(s, f)

        # 6) registra il codice HEX in colors.json se è nuovo
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

@app.get("/api/spools")  # alias per la UI
async def api_spools_alias():
    return await inventory()

# ---------- Slice demo ----------
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
            "PrusaSlicer",
            "--export-gcode",
            "--load",
            "/profiles/print.ini",
            "--load",
            "/profiles/filament.ini",
            "--load",
            "/profiles/printer.ini",
            "--output",
            out_path,
            in_path,
        ]
        if preset_print:
            args.extend(["--preset", preset_print])
        if preset_filament:
            args.extend(["--preset", preset_filament])
        if preset_printer:
            args.extend(["--preset", preset_printer])

        try:
            res = subprocess.run(args, capture_output=True, text=True, timeout=600)
        except FileNotFoundError:
            raise HTTPException(status_code=500, detail="PrusaSlicer non trovato nel container.")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="PrusaSlicer ha impiegato troppo tempo.")

        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Errore PrusaSlicer: {res.stderr[:500]}")

        if not os.path.exists(out_path):
            raise HTTPException(status_code=500, detail="G-code non generato.")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as f:
            gcode = f.read()

        return PlainTextResponse(gcode)
