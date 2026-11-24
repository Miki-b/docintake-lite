from app import pipeline
from app.ocr import OcrResult

SAMPLE_TEXT = """VALLEY REGIONAL LABORATORY
Clinical Chemistry Report
Patient: Maria Gonzalez
MRN: 0048715
Collected: 2026-03-14
HbA1c 7.8 % 4.0-5.6 H
Glucose 142 mg/dL 70-99 H
Hemoglobin 13.9 g/dL 13.5-17.5 N
Potassium 3.1 mmol/L 3.5-5.1 L
"""


def test_pipeline_extract_and_fhir(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "ocr_pdf",
        lambda b: OcrResult(text=SAMPLE_TEXT, engine="mock", mean_confidence=0.99),
    )
    res = pipeline.process_pdf(b"fake-pdf", clinic_id=1, filename="x.pdf", persist=False)

    assert res["fields"]["name"]["value"] == "Maria Gonzalez"
    assert res["fields"]["name"]["verified"] is True
    assert res["fields"]["mrn"]["value"] == "0048715"
    assert res["fields"]["date"]["value"] == "2026-03-14"

    assert len(res["observations"]) == 4
    assert all(r["verified"] for r in res["rows"])
    # LOINC present on the HbA1c observation.
    hba1c = next(o for o in res["observations"] if o["code"].get("text") == "HbA1c")
    assert hba1c["code"]["coding"][0]["code"] == "4548-4"
