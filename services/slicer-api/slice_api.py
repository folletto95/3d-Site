from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import PlainTextResponse
import subprocess, shutil, uuid, pathlib

IN_DIR  = pathlib.Path("/in")
OUT_DIR = pathlib.Path("/out")
PROF    = pathlib.Path("/profiles")
LOGS    = pathlib.Path("/logs")

app = FastAPI()

def run_ps(args):
    return subprocess.run(args, capture_output=True, text=True)

@app.post("/slice", response_class=PlainTextResponse)
async def slice_file(
    model: UploadFile | None = File(default=None),
    model_path: str | None = Form(default=None),
    out_name: str = Form(default="job.gcode"),
    printer_cfg: str = Form(default="/profiles/printer.ini"),
    print_cfg:   str = Form(default="/profiles/print.ini"),
    filament_cfg:str = Form(default="/profiles/filament.ini")
):
    IN_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    if model:
        tmpname = f"{uuid.uuid4()}_{model.filename}"
        dst = IN_DIR / tmpname
        with dst.open("wb") as f:
            shutil.copyfileobj(model.file, f)
        model_file = str(dst)
    elif model_path:
        model_file = model_path
    else:
        return PlainTextResponse("Missing model", status_code=400)

    out_path = OUT_DIR / out_name
    cmd = [
        "/usr/bin/prusa-slicer", "--no-gui",
        "--load", printer_cfg, "--load", print_cfg, "--load", filament_cfg,
        "-g", model_file, "-o", str(out_path)
    ]
    p = run_ps(cmd)
    (LOGS / (out_name + ".stdout.log")).write_text(p.stdout)
    (LOGS / (out_name + ".stderr.log")).write_text(p.stderr)

    if p.returncode != 0 or not out_path.exists():
        return PlainTextResponse("PrusaSlicer failed.\n" + p.stderr, status_code=500)

    return str(out_path)
