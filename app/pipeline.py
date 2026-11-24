"""Ingest pipeline: OCR -> extract -> ground -> FHIR -> store (RLS-scoped).

Grounding guarantee: a lab row's Observation is stored with verified=True only
when the extracted value was found in the OCR text.
"""
from __future__ import annotations

from app import db
from app.extract import Extraction, extract
from app.fhir import build_observation, validate_observation
from app.ocr import ocr_pdf


def build_observations(ex: Extraction, subject_ref: str | None = None) -> list[dict]:
    """Validated FHIR Observations for every readable lab row (value present)."""
    out: list[dict] = []
    for row in ex.rows:
        if row.value is None:
            continue
        obs = build_observation(
            test=row.test,
            value=row.value,
            unit=row.unit,
            reference_range=row.reference_range,
            flag=row.flag,
            subject_ref=subject_ref,
        )
        validate_observation(obs)  # raises if the resource is not valid FHIR
        out.append({"fhir": obs, "verified": row.verified})
    return out


def _fields_payload(ex: Extraction) -> dict:
    return {
        "name": {"value": ex.name.value, "verified": ex.name.verified},
        "mrn": {"value": ex.mrn.value, "verified": ex.mrn.verified},
        "date": {"value": ex.date.value, "verified": ex.date.verified},
    }


def process_pdf(pdf_bytes: bytes, clinic_id: int, filename: str | None = None,
                persist: bool = True) -> dict:
    """Run the full pipeline. If persist, write to Postgres under clinic RLS."""
    ocr = ocr_pdf(pdf_bytes)
    ex = extract(ocr.text)
    observations = build_observations(ex)

    result = {
        "clinic_id": clinic_id,
        "filename": filename,
        "ocr_engine": ocr.engine,
        "mean_confidence": ocr.mean_confidence,
        "fields": _fields_payload(ex),
        "rows": [
            {
                "test": r.test,
                "value": r.value,
                "unit": r.unit,
                "reference_range": r.reference_range,
                "flag": r.flag,
                "verified": r.verified,
            }
            for r in ex.rows
        ],
        "observations": [o["fhir"] for o in observations],
        "patient_id": None,
        "document_id": None,
    }
    if not persist:
        return result

    name = ex.name.value or "Unknown"
    mrn = ex.mrn.value or "UNKNOWN"
    with db.clinic_session(clinic_id) as cur:
        patient_id = db.upsert_patient(cur, clinic_id, name, mrn)
        document_id = db.insert_document(cur, clinic_id, patient_id, filename, ocr.engine)
        subject_ref = f"Patient/{patient_id}"
        for o in observations:
            fhir = dict(o["fhir"])
            fhir["subject"] = {"reference": subject_ref}
            db.insert_observation(cur, clinic_id, patient_id, document_id, fhir, o["verified"])
    result["patient_id"] = patient_id
    result["document_id"] = document_id
    for obs in result["observations"]:
        obs["subject"] = {"reference": f"Patient/{patient_id}"}
    return result
