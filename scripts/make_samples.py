"""Generate synthetic lab-report PDFs (clean + "scanned") and a truth.json.

Run:  python scripts/make_samples.py
Output: samples/*.pdf and samples/truth.json

All data is synthetic. Two reports are rendered to a rasterised, slightly
rotated + noisy image and re-embedded in a PDF to emulate a scan, so OCR is
actually required (no text layer survives).
"""
from __future__ import annotations

import io
import json
import random
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Image as RLImage,
)
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples"
RNG = random.Random(42)
np.random.seed(42)

# (test display name, unit [UCUM], ref_low, ref_high)
TEST_DEFS = {
    "HbA1c": ("%", 4.0, 5.6),
    "Glucose": ("mg/dL", 70.0, 99.0),
    "Hemoglobin": ("g/dL", 13.5, 17.5),
    "Potassium": ("mmol/L", 3.5, 5.1),
}

# Four synthetic patients. scanned=True -> rasterised noisy "scan".
PATIENTS = [
    {
        "filename": "report_01_clean.pdf",
        "scanned": False,
        "name": "Maria Gonzalez",
        "mrn": "0048715",
        "date": "2026-03-14",
        "values": {"HbA1c": 7.8, "Glucose": 142, "Hemoglobin": 13.9, "Potassium": 3.1},
    },
    {
        "filename": "report_02_clean.pdf",
        "scanned": False,
        "name": "James Carter",
        "mrn": "1189223",
        "date": "2026-05-02",
        "values": {"HbA1c": 5.2, "Glucose": 88, "Hemoglobin": 15.1, "Potassium": 4.4},
    },
    {
        "filename": "report_03_scanned.pdf",
        "scanned": True,
        "name": "Wei Chen",
        "mrn": "2201456",
        "date": "2026-07-19",
        "values": {"HbA1c": 6.4, "Glucose": 105, "Hemoglobin": 12.8, "Potassium": 5.6},
    },
    {
        "filename": "report_04_scanned.pdf",
        "scanned": True,
        "name": "Linda Thompson",
        "mrn": "3309871",
        "date": "2026-09-08",
        "values": {"HbA1c": 9.1, "Glucose": 201, "Hemoglobin": 16.2, "Potassium": 4.0},
    },
]


def flag_for(value: float, low: float, high: float) -> str:
    if value < low:
        return "L"
    if value > high:
        return "H"
    return "N"


def fmt_value(test: str, value: float) -> str:
    # Integers for mg/dL glucose, one decimal otherwise.
    if test == "Glucose":
        return str(int(value))
    return f"{value:.1f}"


def build_rows(patient: dict) -> list[dict]:
    rows = []
    for test, value in patient["values"].items():
        unit, low, high = TEST_DEFS[test]
        rows.append(
            {
                "test": test,
                "value": fmt_value(test, value),
                "unit": unit,
                "reference_range": f"{low:g}-{high:g}",
                "ref_low": low,
                "ref_high": high,
                "flag": flag_for(value, low, high),
            }
        )
    return rows


def render_pdf(patient: dict, rows: list[dict], out: io.BytesIO | Path) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(
        out if isinstance(out, io.BytesIO) else str(out),
        pagesize=letter,
        topMargin=0.8 * inch,
    )
    story = [
        Paragraph("VALLEY REGIONAL LABORATORY", styles["Title"]),
        Paragraph("Clinical Chemistry Report", styles["Heading2"]),
        Spacer(1, 0.2 * inch),
        Paragraph(f"Patient: {patient['name']}", styles["Normal"]),
        Paragraph(f"MRN: {patient['mrn']}", styles["Normal"]),
        Paragraph(f"Collected: {patient['date']}", styles["Normal"]),
        Spacer(1, 0.3 * inch),
    ]
    table_data = [["Test", "Value", "Unit", "Reference Range", "Flag"]]
    for r in rows:
        table_data.append(
            [r["test"], r["value"], r["unit"], r["reference_range"], r["flag"]]
        )
    table = Table(table_data, colWidths=[1.6 * inch, 0.9 * inch, 0.9 * inch, 1.6 * inch, 0.6 * inch])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f4f6")]),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(
            "Synthetic report for prototype testing. Not a real patient.",
            styles["Italic"],
        )
    )
    doc.build(story)


def scanify(clean_pdf_bytes: bytes, out_path: Path) -> None:
    """Rasterise page 1, add slight rotation + noise, re-embed as a PDF."""
    pdf = pdfium.PdfDocument(clean_pdf_bytes)
    page = pdf[0]
    bitmap = page.render(scale=200 / 72)  # ~200 DPI
    img = bitmap.to_pil().convert("L")  # grayscale like a scan

    # Slight rotation (fill with paper-white).
    angle = RNG.uniform(-2.0, 2.0)
    img = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=255)

    # Gaussian noise.
    arr = np.asarray(img).astype(np.float32)
    arr += np.random.normal(0, 10, arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)

    # Re-embed full-page image into a new PDF.
    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)

    w, h = img.size
    aspect = h / w
    doc = SimpleDocTemplate(str(out_path), pagesize=letter, topMargin=0.3 * inch, bottomMargin=0.3 * inch)
    page_w = letter[0] - 0.6 * inch
    doc.build([RLImage(img_buf, width=page_w, height=page_w * aspect)])
    pdf.close()


def main() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    truth = []
    for patient in PATIENTS:
        rows = build_rows(patient)
        out_path = SAMPLES_DIR / patient["filename"]
        if patient["scanned"]:
            buf = io.BytesIO()
            render_pdf(patient, rows, buf)
            scanify(buf.getvalue(), out_path)
        else:
            render_pdf(patient, rows, out_path)

        truth.append(
            {
                "filename": patient["filename"],
                "scanned": patient["scanned"],
                "name": patient["name"],
                "mrn": patient["mrn"],
                "date": patient["date"],
                "rows": [
                    {k: r[k] for k in ("test", "value", "unit", "reference_range", "flag")}
                    for r in rows
                ],
            }
        )
        print(f"wrote {out_path.name} ({'scanned' if patient['scanned'] else 'clean'})")

    truth_path = SAMPLES_DIR / "truth.json"
    truth_path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    print(f"wrote {truth_path.name} with {len(truth)} reports")


if __name__ == "__main__":
    main()
