from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
from pathlib import Path
import subprocess, tempfile, re, math, os, shutil

app = FastAPI(title="PrusaSlicer Headless Service")

# Profili fissi montati in /profiles (RO)
PRINTER_INI  = os.environ.get("PRINTER_INI",  "/profiles/printer.ini")
FILAMENT_INI = os.environ.get("FILAMENT_INI", "/profiles/filament.ini")
PRINT_INI    = os.environ.get("PRINT_INI",    "/profiles/print.ini")

# Parametri costo (puoi sovrascriverli via env o integrarli con Spoolman dal tuo backend)
COSTO_EUR_AL_KWH   = float(os.environ.get("COSTO_EUR_AL_KWH", "0.30"))
WATT_STIMATI       = float(os.environ.get("WATT_STIMATI", "80"))
COSTO_EUR_AL_KG    = float(os.environ.get("COSTO_EUR_AL_KG", "20.0"))
MARGINE_PERCENT    = float(os.environ.get("MARGINE_PERCENT", "25.0"))

PS_BIN = os.environ.get("PS_BIN", "/usr/local/bin/ps-headless")

def parse_gcode_metrics(gcode_text: str):
    # tempo
    time_h, time_m, time_s = 0,0,0
    m = re.search(r"estimated printing time *= *(\d+)h *(\d+)m *(\d+)s", gcode_text, re.IGNORECASE)
    if m:
        time_h, time_m, time_s = map(int, m.groups())
    else:
        m2 = re.search(r"; *TIME: *(\d+)", gcode_text)
        if m2:
            sec = int(m2.group(1))
            time_h, rem = divmod(sec, 3600)
            time_m, time_s = divmod(rem, 60)

    # grammi
    grams = None
    g = re.search(r"filament used \[g\] *= *([0-9]+(?:\.[0-9]+)?)", gcode_text, re.IGNORECASE)
    if g:
        grams = float(g.group(1))
    else:
        mm = re.search(r"filament used \[mm\] *= *([0-9]+(?:\.[0-9]+)?)", gcode_text, re.IGNORECASE)
        if mm:
            length_mm = float(mm.group(1))
            r = 1.75 / 2.0
            area_mm2 = math.pi * r * r
            vol_mm3 = length_mm * area_mm2
            vol_cm3 = vol_mm3 / 1000.0
            grams = vol_cm3 * 1.24  # PLA indicativo

    seconds = time_h*3600 + time_m*60 + time_s
    return seconds, grams

def stima_costi(seconds: int, grams: float):
    ore = seconds / 3600.0
    costo_energia = (WATT_STIMATI / 1000.0) * ore * COSTO_EUR_AL_KWH
    costo_materiale = (grams / 1000.0) * COSTO_EUR_AL_KG if grams is not None else 0.0
    base = costo_energia + costo_materiale
    totale = base * (1.0 + MARGINE_PERCENT/100.0)
    return {
        "ore": ore,
        "costo_energia": round(costo_energia, 2),
        "costo_materiale": round(costo_materiale, 2),
        "costo_base": round(base, 2),
        "costo_totale": round(totale, 2)
    }

@app.post("/slice")
async def slice_model(
    model: UploadFile = File(..., description="STL/3MF/AMF/OBJ/STEP (se supportato)"),
    return_gcode: bool = Form(False),
):
    for p in (PRINTER_INI, FILAMENT_INI, PRINT_INI):
        if not Path(p).exists():
            raise HTTPException(500, f"Profilo mancante: {p}")

    with tempfile.TemporaryDirectory(dir="/work") as tmpdir:
        tmp = Path(tmpdir)
        in_path = tmp / model.filename
        out_gcode = tmp / "out.gcode"

        with open(in_path, "wb") as f:
            shutil.copyfileobj(model.file, f)

        cmd = [
            PS_BIN,
            "--no-gui",
            "--load", PRINTER_INI,
            "--load", FILAMENT_INI,
            "--load", PRINT_INI,
            "--export-gcode",
            "-o", str(out_gcode),
            str(in_path),
        ]

        try:
            cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "Timeout slicing")

        if cp.returncode != 0 or not out_gcode.exists():
            err = (cp.stderr or "") + "\n" + (cp.stdout or "")
            raise HTTPException(500, f"Slicing fallito.\n{err[-4000:]}")

        gcode_text = out_gcode.read_text(errors="ignore")
        seconds, grams = parse_gcode_metrics(gcode_text)
        costi = stima_costi(seconds, grams if grams is not None else 0.0)

        payload = {
            "filename": model.filename,
            "seconds": seconds,
            "estimated_time_hms": f"{seconds//3600}h {(seconds%3600)//60}m {seconds%60}s",
            "filament_g": round(grams, 2) if grams is not None else None,
            "cost": costi
        }

        if return_gcode:
            return JSONResponse({**payload, "gcode": gcode_text[:200000]})

        return JSONResponse(payload)
