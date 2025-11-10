import os
import typing as T
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, Form
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
import httpx

APP_DIR = Path(__file__).parent
WEB_DIR = APP_DIR / "web"

# Env
SPOOLMAN = os.environ.get("SPOONMAN_URL") or os.environ.get("SPOONMAN_URL") or "http://192.168.10.164:7912"
HOURLY_RATE = float(os.environ.get("HOURLY_RATE", "1"))
CURRENCY = os.environ.get("CURRENCY", "EUR")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "info").lower()

app = FastAPI(title="3D Site API", version="1.0.0")

# /ui static
if WEB_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(WEB_DIR), html=True), name="ui")

# --------- Utils ---------
def _norm_hex(h: T.Optional[str]) -> str:
    if not h:
        return "#777777"
    h = h.strip()
    if not h.startswith("#"):
        h = "#" + h
    if len(h) == 4:  # #rgb -> #rrggbb
        h = "#" + "".join([c*2 for c in h[1:]])
    return h.upper()

def _is_transparent(material: str, color_name: str, is_transparent_flag: T.Optional[bool]) -> bool:
    if is_transparent_flag:
        return True
    text = f"{material} {color_name}".lower()
    for key in ("translucent", "transparent", "trasparente"):
        if key in text:
            return True
    return False

# --------- Spoolman fetch with fallbacks ---------
SPOOL_ENDPOINTS = [
    "/api/v1/spool/?page_size=1000",
    "/api/v1/spools?page_size=1000",
    "/api/spool/?page_size=1000",
    "/api/spools?page_size=1000",
]

async def fetch_spools() -> T.List[dict]:
    """
    Tenta più endpoint noti di Spoolman e normalizza il campo results.
    Restituisce lista di spools raw.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, connect=3.0)) as client:
        last_err = None
        for ep in SPOOL_ENDPOINTS:
            url = SPOOLMAN.rstrip("/") + ep
            try:
                r = await client.get(url)
                r.raise_for_status()
                data = r.json()
                # Possibili chiavi: "results", "items", "spools", …
                if isinstance(data, dict):
                    for key in ("results", "items", "spools", "data"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                if isinstance(data, list):
                    return data
                # Se qui, risposta strana
                last_err = RuntimeError(f"Formato sconosciuto da {url}")
            except Exception as e:
                last_err = e
        raise HTTPException(
            status_code=502,
            detail=f"Spoolman non raggiungibile. "
                   f"Tentativi: {[SPOOLMAN + ep for ep in SPOOL_ENDPOINTS]}  Errore: {type(last_err).__name__}: {last_err}"
        )

def _val(x, *names, default=None):
    """
    Estrae un valore da dict annidati provando più path.
    Esempio: _val(sp, ("filament","material"), ("material",), default="")
    """
    if not isinstance(x, dict):
        return default
    for name in names:
        cur = x
        ok = True
        for p in (name if isinstance(name, (list, tuple)) else [name]):
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                ok = False
                break
        if ok:
            return cur
    return default

def _norm_item(sp: dict) -> dict:
    """
    Normalizza un singolo spool in un oggetto 'item' coerente con la UI.
    """
    # campi possibili
    filament = _val(sp, "filament", default={}) or {}
    material = _val(sp, ("filament","material"), "material", ("filament","type"), default="") or ""
    diameter = _val(sp, ("filament","diameter"), "diameter", default=1.75)
    color_hex = _norm_hex(_val(sp, ("filament","color_hex"), "color_hex", default="#777777"))
    color_name = _val(sp, ("filament","color"), ("filament","color_name"), "color_name", "color", default="") or ""
    is_transp = _is_transparent(material, color_name, _val(sp, "is_transparent", default=None))

    # pesi / costi
    # Spoolman ha varianti: "remaining_weight_g", "remaining_g", "remaining_weight"
    remaining_g = _val(sp, "remaining_weight_g", "remaining_g", "remaining_weight", default=None)
    if remaining_g is None:
        # fallback peso totale - usato
        total_g = _val(sp, "initial_weight_g", "weight", default=None)
        used_g  = _val(sp, "used_weight_g", "used", default=None)
        if total_g is not None and used_g is not None:
            remaining_g = max(0, float(total_g) - float(used_g))
    try:
        remaining_g = int(round(float(remaining_g))) if remaining_g is not None else None
    except:
        remaining_g = None

    # prezzo/kg: priorità a campi espliciti
    price_per_kg = _val(sp, "price_per_kg", ("filament","price_per_kg"), default=None)
    if price_per_kg is None:
        # calcolo rozzo se abbiamo prezzo spool e peso
        price_eur = _val(sp, "price", default=None)
        weight_g  = _val(sp, "weight_g", "initial_weight_g", default=None)
        if price_eur is not None and weight_g:
            try:
                price_per_kg = float(price_eur) / (float(weight_g)/1000.0)
            except:
                price_per_kg = None
    try:
        price_per_kg = round(float(price_per_kg), 2) if price_per_kg is not None else None
    except:
        price_per_kg = None

    # nome "umano": se vuoto, ci pensa il frontend a derivarlo da HEX
    return {
        "count": 1,
        "remaining_g": remaining_g,
        "price_per_kg": price_per_kg,
        "color_hex": color_hex,
        "color_name": color_name if color_name else None,
        "material": str(material or "").strip() or "N/D",
        "diameter": str(diameter),
        "is_transparent": bool(is_transp),
        "currency": CURRENCY,
    }

def _group_items(items: T.List[dict]) -> T.List[dict]:
    """
    Raggruppa per (material, color_hex, diameter, is_transparent, color_name) sommando quantità e count.
    """
    from collections import defaultdict
    acc = defaultdict(lambda: {"count":0, "remaining_g":0, "price_per_kg":None, "currency":CURRENCY})
    def key(it):
        return (
            it.get("material",""),
            it.get("color_hex","#777777").upper(),
            it.get("diameter","1.75"),
            bool(it.get("is_transparent", False)),
            it.get("color_name") or None,
        )
    for it in items:
        k = key(it)
        node = acc[k]
        node["count"] += 1
        if isinstance(it.get("remaining_g"), (int,float)):
            node["remaining_g"] += int(round(float(it["remaining_g"])))
        # scegli un price_per_kg non-null (il primo disponibile)
        if node["price_per_kg"] is None and it.get("price_per_kg") is not None:
            node["price_per_kg"] = it["price_per_kg"]
    # ricostruzione oggetti
    out = []
    for k, node in acc.items():
        material, color_hex, diameter, is_transparent, color_name = k
        out.append({
            "count": node["count"],
            "remaining_g": node["remaining_g"] if node["remaining_g"] else None,
            "price_per_kg": node["price_per_kg"],
            "color_hex": color_hex,
            "color_name": color_name,
            "material": material,
            "diameter": str(diameter),
            "is_transparent": bool(is_transparent),
            "currency": node["currency"],
        })
    # ordina per material, poi colore
    out.sort(key=lambda x: (x["material"], x["color_hex"]))
    return out

# --------- Routes ---------

@app.get("/", response_class=PlainTextResponse)
async def root():
    return "3D Site API alive. Visit /ui/"

@app.get("/health", response_class=JSONResponse)
async def health():
    return {"status":"ok","spoolman":SPOOLMAN,"hourly_rate":HOURLY_RATE,"currency":CURRENCY}

@app.get("/ui/", response_class=HTMLResponse)
async def ui_index():
    index_path = WEB_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "index.html non trovato")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))

@app.get("/inventory", response_class=JSONResponse)
@app.get("/api/spools", response_class=JSONResponse)
async def inventory():
    spools = await fetch_spools()
    items = [_norm_item(sp) for sp in spools]
    grouped = _group_items(items)
    return {"items": grouped, "hourly_rate": HOURLY_RATE, "currency": CURRENCY}

# Endpoint di slice (placeholder per ora)
@app.post("/slice", response_class=PlainTextResponse)
async def slice_model(
    file: UploadFile,
    filament_hex: str = Form(default="#FFFFFF"),
    material: str = Form(default="PLA"),
    nozzle: float = Form(default=0.4),
):
    # TODO: integrare curaengine/prusaslicer CLI
    return f"Slice richiesto: {file.filename} / {material} {filament_hex} nozzle={nozzle}"
