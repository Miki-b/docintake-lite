"""FastAPI surface for DocIntake Lite.

  POST /documents              multipart PDF + header X-Clinic-Id
                               -> OCR -> extract -> FHIR -> store
                               returns fields (with verified flags) + Observations
  GET  /patients/{id}/observations   (RLS-scoped by X-Clinic-Id)
  GET  /health
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.pipeline import process_pdf

app = FastAPI(title="DocIntake Lite", version="0.1.0")

# Serve the generated synthetic sample PDFs so the hosted demo is self-contained
# (someone can grab e.g. /samples/report_01_clean.pdf and upload it via /docs).
_SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
if _SAMPLES_DIR.is_dir():
    app.mount("/samples", StaticFiles(directory=str(_SAMPLES_DIR)), name="samples")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    # Open straight into the interactive Swagger UI (the demo surface).
    return RedirectResponse(url="/docs")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/documents")
async def post_document(
    file: UploadFile = File(...),
    x_clinic_id: int = Header(..., alias="X-Clinic-Id"),
) -> dict:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="empty upload")
    try:
        return process_pdf(content, clinic_id=x_clinic_id, filename=file.filename)
    except Exception as exc:  # noqa: BLE001
        # Avoid leaking PHI in error text.
        raise HTTPException(
            status_code=500, detail=f"processing failed: {type(exc).__name__}"
        ) from None


@app.get("/patients/{patient_id}/observations")
def get_observations(
    patient_id: int,
    x_clinic_id: int = Header(..., alias="X-Clinic-Id"),
) -> dict:
    with db.clinic_session(x_clinic_id) as cur:
        rows = db.fetch_observations(cur, patient_id)
    return {"patient_id": patient_id, "count": len(rows), "observations": rows}
