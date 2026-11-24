"""Evaluate OCR + extraction accuracy against samples/truth.json.

Run:  python scripts/eval.py
Prints field-level accuracy for clean vs scanned PDFs and the OCR engine used.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.extract import extract, normalize  # noqa: E402
from app.ocr import ocr_pdf  # noqa: E402

SAMPLES = ROOT / "samples"


def _name_match(got: str | None, want: str) -> bool:
    return got is not None and normalize(got) == normalize(want)


def _eq(got: str | None, want: str) -> bool:
    return got is not None and normalize(got) == normalize(want)


def _value_eq(got: str | None, want: str) -> bool:
    if got is None:
        return False
    try:
        return abs(float(got) - float(want)) < 1e-6
    except ValueError:
        return normalize(got) == normalize(want)


def evaluate_report(pdf_bytes: bytes, truth: dict) -> dict:
    ocr = ocr_pdf(pdf_bytes)
    ex = extract(ocr.text)

    results: dict[str, bool] = {
        "name": _name_match(ex.name.value, truth["name"]),
        "mrn": _eq(ex.mrn.value, truth["mrn"]),
        "date": _eq(ex.date.value, truth["date"]),
    }
    got_rows = {r.test: r for r in ex.rows}
    for row in truth["rows"]:
        test = row["test"]
        got = got_rows.get(test)
        results[f"lab:{test}"] = _value_eq(got.value if got else None, row["value"])

    verified = sum(1 for r in ex.rows if r.verified)
    return {
        "engine": ocr.engine,
        "mean_confidence": ocr.mean_confidence,
        "results": results,
        "verified_rows": verified,
        "extracted_rows": len(ex.rows),
    }


def main() -> None:
    truth = json.loads((SAMPLES / "truth.json").read_text(encoding="utf-8"))
    buckets = {"clean": [], "scanned": []}
    engine = None
    for rec in truth:
        pdf_bytes = (SAMPLES / rec["filename"]).read_bytes()
        rep = evaluate_report(pdf_bytes, rec)
        engine = rep["engine"]
        bucket = "scanned" if rec["scanned"] else "clean"
        buckets[bucket].append((rec, rep))
        correct = sum(rep["results"].values())
        total = len(rep["results"])
        conf = rep["mean_confidence"]
        conf_s = f"{conf:.2f}" if conf is not None else "n/a"
        print(
            f"  {rec['filename']:<22} {bucket:<8} "
            f"{correct}/{total} fields  conf={conf_s}  "
            f"verified {rep['verified_rows']}/{rep['extracted_rows']} rows"
        )

    print(f"\nOCR engine: {engine}\n")
    overall_c = overall_t = 0
    for bucket, items in buckets.items():
        c = sum(sum(r["results"].values()) for _, r in items)
        t = sum(len(r["results"]) for _, r in items)
        overall_c += c
        overall_t += t
        if t:
            print(f"{bucket:<8} accuracy: {c}/{t} = {100 * c / t:.1f}%")
    if overall_t:
        print(f"{'overall':<8} accuracy: {overall_c}/{overall_t} = {100 * overall_c / overall_t:.1f}%")


if __name__ == "__main__":
    main()
