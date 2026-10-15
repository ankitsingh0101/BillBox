"""BillBox web app:  uvicorn app:app --reload   then open http://localhost:8000

Data handling: nothing is stored on the server. Uploaded files live in a temp folder only while the
model reads them, then are deleted. Results stay in the browser tab until the user clears them."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import requests
from fastapi import FastAPI, File, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from starlette.background import BackgroundTask

from billbox import extractor, pipeline
from billbox.export import build_workbook

app = FastAPI(title="BillBox")
STATIC = Path(__file__).parent / "static"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/", response_class=HTMLResponse)
def home():
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health():
    model = extractor.MODEL
    try:
        r = requests.get(f"{extractor.OLLAMA_URL}/api/tags", timeout=2)
        r.raise_for_status()
        names = [m.get("name", "") for m in r.json().get("models", [])]
        return {"ollama": True, "model": model, "installed": model in names or f"{model}:latest" in names}
    except Exception:
        return {"ollama": False, "model": model, "installed": False}


@app.post("/api/process")
async def process(files: list[UploadFile] = File(...)):
    bills = []
    with tempfile.TemporaryDirectory() as tmp:      # deleted automatically when this block ends
        for f in files:
            p = Path(tmp) / Path(f.filename or "upload").name
            p.write_bytes(await f.read())
            bills.extend(pipeline.process_file(p))
    return {"bills": bills}


@app.post("/api/check")
async def check(payload: dict):
    return {"bills": pipeline.recheck(payload.get("bills", []))}


@app.post("/api/export")
async def export(payload: dict):
    bills = pipeline.recheck(payload.get("bills", []))
    tmp = Path(tempfile.mkdtemp(prefix="billbox_"))
    out = tmp / "billbox_export.xlsx"
    build_workbook(bills, str(out))
    return FileResponse(out, filename="billbox_export.xlsx", media_type=XLSX,
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))  # deleted after download