from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import os, tempfile, subprocess, re, colorsys
import httpx

app = FastAPI(title="slicer-api", version="0.8.0")

# -------- UI --------
app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")

@app.get("/health", response_class=PlainTextResponse, include_in_schema=False)
def health():
    return "ok"

# -------- Config (come prima) --------
CURRENCY    = os.getenv("CURRENCY", "EUR")
HOURLY_RATE = float(os.getenv("HOURLY_RATE", "1"))

def _no_cache(payload: dict):
    return JSONResponse(content=payload, headers={"Cache-Control":"no-store, max-age=0"})

# -------- Util colore --------
def _normalize_hex(h: str | None) -> str | None:
    if not h: return None
    s = str(h).strip()
    if not s: return None
    if not s.startswith("#"):
        s = "#" + s
    # "#FFF" -> "#FFFFFF"
    if len(s) == 4 and s.startswith("#"):
        r, g, b = s[1], s[2], s[3]
        s = f"#{r}{r}{g}{g}{b}{b}"
    return s.upper()[:7]

def _hex_to_name(h: str) -> str:
    """Heuristica in IT più tollerante: banda arancione più stretta,
    'rosa' corretta (300–350°), bianchi/neri/grigi gestiti meglio."""
    h = _normalize_hex(h)
    if not h: return "Grigio"
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

    h_, l, s = colorsys.rgb_to_hls(r, g, b)
    deg = (h_ * 360.0) % 360.0

    # zone poco sature → scala di grigi
    if s < 0.10:
        if l > 0.90: return "Bianco"
        if l < 0.10: return "Nero"
        return "Grigio"

    # mappa “stretta” sulle tinte
    if 350 <= deg or deg < 10:   return "Rosso"
    if 10 <= deg < 25:           return "Rosso"    # rosso caldo, evita falsi 'arancione'
    if 25 <= deg < 50:           return "Arancione"
    if 50 <= deg < 90:           return "Giallo"
    if 90 <= deg < 170:          return "Verde"
    if 170 <= deg < 200:         return "Ciano"
    if 200 <= deg < 260:         return "Blu"
    if 260 <= deg < 300:         return "Viola"
    if 300 <= deg < 350:         return "Rosa"
    return "Grigio"

# parole che identificano chiaramente trasparenza
TRANSPAT = re.compile(
    r"\b(clear|transparent|traspar|translucent|translucido|semi[-\s]?traspar|glass|smoke)\b",
    re.I
)

def _detect_transparent(spool: dict, filament: dict, color_hex: str | None) -> bool:
    blob = " ".join([
        str(spool.get("name","")),
        str(spool.get("product","")),
        str(spool.get("color","")),
        str(spool.get("color_name","")),
        str(filament.get("name","")),
        str(filament.get("material",""))
    ])
    if TRANSPAT.search(blob):
        return True

    # euristica: PETG + 'Translucent' spesso bianco ma in realtà chiaro/trasparente
    mat = (filament.get("material") or spool.get("material") or "").lower()
    if "petg" in mat and "transluc" in mat:
        return True

    # se è quasi bianco e il testo sopra suggerisce trasparenza
    hx = _normalize_hex(color_hex)
    if hx:
        try:
            r = int(hx[1:3],16); g = int(hx[3:5],16); b = int(hx[5:7],16)
            if max(r,g,b) > 248 and TRANSPAT.search(blob):
                return True
        except Exception:
            pass
    return False

def _first(d: dict, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d[k]

def _bases_from_env():
    base_env = (os.getenv("SPOOLMAN_URL") or "").rstrip("/")
    if not base_env:
        base_env = "http://192.168.10.164:7912"
    if base_env.startswith(("http://", "https://")):
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

def _price_per_kg_from_spool(spool, filament):
    spool_price = _first(spool, ["purchase_price","price","spool_price","cost_eur","cost"])
    weight_g    = _first(filament, ["weight","weight_g"])
    if spool_price is not None and weight_g:
        try:
            return float(spool_price) / (float(weight_g) / 1000.0)
        except Exception:
            return None
    return _first(filament, ["price_per_kg","cost_per_kg"])

def _extract_filament_from_spool(spool):
    f = spool.get("filament")
    if isinstance(f, dict) and f:
        return f
    # legacy flatten (best effort)
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

# -------- INVENTORY (compat UI) --------
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

    spools = data.get("results") or data.get("spools") if isinstance(data, dict) else data
    spools = spools or []

    items = []
    for s in spools:
        f = _extract_filament_from_spool(s)

        color_hex = _normalize_hex(_first(s,["color_hex"]) or f.get("color_hex")) or "#777777"
        material  = f.get("material") or s.get("material") or "N/A"
        diameter  = str(f.get("diameter") or s.get("diameter") or "")

        # trasparenza robusta (Translucent, Clear, ecc.)
        is_trans  = _detect_transparent(s, f, color_hex)

        # nome colore (se non fornito, stimato dall'HEX con nuova mappa)
        color_name = _first(s, ["color_name","colour_name"]) or f.get("color_name") or f.get("colour_name")
        if is_trans:
            color_name = "Trasparente"
        if not color_name:
            color_name = _hex_to_name(color_hex)

        price_per_kg = _price_per_kg_from_spool(s, f)

        items.append({
            # compat per UI:
            "hex": color_hex,            # ← usato dai “pallini”
            "name": color_name,          # ← etichetta colore

            # info extra (manteniamo i vecchi campi)
            "color_hex": color_hex,
            "color_name": color_name,
            "material": material,
            "diameter": diameter,
            "count": 1,
            "remaining_g": float(_first(s,["remaining_weight","remaining_weight_g"]) or 0.0),
            "price_per_kg": float(price_per_kg) if price_per_kg is not None else None,
            "currency": CURRENCY,
            "is_transparent": bool(is_trans),
        })

    # merge per (hex, material, diameter, is_transparent)
    merged = {}
    for it in items:
        key = (it["hex"], it["material"], it["diameter"], it["is_transparent"])
        b = merged.setdefault(key, {"count":0,"remaining_g":0.0,"price_per_kg":None,
                                    "hex":it["hex"],"name":it["name"],
                                    "color_hex":it["color_hex"],"color_name":it["color_name"],
                                    "material":it["material"],"diameter":it["diameter"],
                                    "is_transparent":it["is_transparent"],"currency":CURRENCY})
        b["count"] += 1
        b["remaining_g"] += it["remaining_g"]
        if it["price_per_kg"] and not b["price_per_kg"]:
            b["price_per_kg"] = it["price_per_kg"]

    out = list(merged.values())
    out.sort(key=lambda x: (x["material"].lower(), x["name"].lower(), x["hex"]))
    return _no_cache({"items": out, "hourly_rate": HOURLY_RATE, "currency": CURRENCY})

# Alias per chi chiama /api/spools
@app.get("/api/spools")
async def api_spools_alias():
    return await inventory()

# -------- Slicing demo --------
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
            subprocess.run(args, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            tail = (e.stderr or e.stdout or "")[-4000:]
            raise HTTPException(500, f"Slicer failed:\n{tail}")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as g:
            return g.read()
