from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
import subprocess, tempfile, os

app = FastAPI(title="slicer-api", version="0.2.0")

# --- UI: serve la cartella /app/web su /ui ---
app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")

@app.get("/", include_in_schema=False)
def root():
    # vai diretto all'interfaccia
    return RedirectResponse(url="/ui/")

@app.get("/healthz", response_class=PlainTextResponse, include_in_schema=False)
def healthz():
    return "ok"

# --- API di slicing di esempio ---
@app.post("/api/slice", response_class=PlainTextResponse)
async def slice_model(
    model: UploadFile = File(..., description="STL/3MF da slicare"),
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
            "--load", "/profiles/print.ini",
            "--load", "/profiles/filament.ini",
            "--load", "/profiles/printer.ini",
            in_path,
            "-o", out_path,
        ]
        if preset_print:    args += ["--load", preset_print]
        if preset_filament: args += ["--load", preset_filament]
        if preset_printer:  args += ["--load", preset_printer]

        try:
            res = subprocess.run(args, check=True, text=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            tail = (e.stderr or e.stdout or "")[-4000:]
            raise HTTPException(status_code=500, detail=f"Slicer failed:\n{tail}")

        with open(out_path, "r", encoding="utf-8", errors="ignore") as g:
            return g.read()
