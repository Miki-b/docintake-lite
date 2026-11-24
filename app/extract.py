"""Rule/regex extraction of patient demographics + lab rows from OCR text,
with grounding: every extracted value must appear in the OCR text (after a
normalisation that tolerates common OCR confusions O/0, l/1, I/1 and spaces).

A field is marked verified=False if it cannot be grounded. Callers must never
persist a lab value as verified unless `verified` is True.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical test names we understand.
KNOWN_TESTS = {
    "hba1c": "HbA1c",
    "glucose": "Glucose",
    "hemoglobin": "Hemoglobin",
    "haemoglobin": "Hemoglobin",
    "potassium": "Potassium",
}

_OCR_TRANS = str.maketrans({"o": "0", "l": "1", "i": "1", "|": "1"})


def normalize(s: str) -> str:
    """Lowercase, fold OCR confusions, drop non-alphanumerics.

    Applied identically to both an extracted value and the OCR text so a
    substring check is a fair 'did this actually appear' grounding test.
    """
    s = s.lower().translate(_OCR_TRANS)
    return re.sub(r"[^a-z0-9]", "", s)


def grounded(value: str, ocr_text: str) -> bool:
    """True iff the normalised value appears in the normalised OCR text."""
    nv = normalize(value)
    return bool(nv) and nv in normalize(ocr_text)


def _digits(token: str) -> str:
    """Fold OCR letter->digit confusions for numeric-ish tokens (MRN)."""
    return token.translate(_OCR_TRANS)


@dataclass
class Field:
    value: str | None
    verified: bool = False


@dataclass
class LabRow:
    test: str
    value: str | None
    unit: str | None
    reference_range: str | None
    flag: str | None
    verified: bool = False  # True only if the value is grounded in the text


@dataclass
class Extraction:
    name: Field
    mrn: Field
    date: Field
    rows: list[LabRow] = field(default_factory=list)


def _find_after_label(lines: list[str], label: str) -> str | None:
    """Return the text after a 'Label:' prefix on the first matching line."""
    for line in lines:
        low = line.lower()
        idx = low.find(label)
        if idx != -1:
            rest = line[idx + len(label):]
            rest = rest.lstrip(" :\t-")
            if rest.strip():
                return rest.strip()
    return None


def extract_name(lines: list[str]) -> str | None:
    raw = _find_after_label(lines, "patient")
    if not raw:
        return None
    # Keep letters, spaces, hyphen, apostrophe. Strip trailing noise.
    cleaned = re.sub(r"[^A-Za-z '\-]", " ", raw).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or None


def extract_mrn(lines: list[str]) -> str | None:
    raw = _find_after_label(lines, "mrn")
    if not raw:
        return None
    token = raw.split()[0] if raw.split() else raw
    folded = _digits(token)
    digits = re.sub(r"[^0-9]", "", folded)
    return digits or None


def extract_date(lines: list[str]) -> str | None:
    # Prefer a value after a 'Collected' label; fall back to any ISO date.
    raw = _find_after_label(lines, "collected")
    candidates = [raw] if raw else []
    candidates.append("\n".join(lines))
    for c in candidates:
        if not c:
            continue
        m = re.search(r"(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})", c)
        if m:
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


# value  unit  low - high  [flag]
_ROW_TAIL = re.compile(
    r"(?P<value>[0-9OlI|]+(?:[.,][0-9OlI|]+)?)\s+"
    r"(?P<unit>%|[A-Za-z]+/?[A-Za-z]*)\s+"
    r"(?P<low>[0-9OlI|]+(?:[.,][0-9OlI|]+)?)\s*[-–—]\s*"
    r"(?P<high>[0-9OlI|]+(?:[.,][0-9OlI|]+)?)\s*"
    r"(?P<flag>[HLN])?\b",
    re.IGNORECASE,
)

# UCUM-ish canonical units keyed by lowercased, de-noised OCR token.
_UNIT_CANON = {
    "%": "%",
    "mg/dl": "mg/dL",
    "g/dl": "g/dL",
    "mmol/l": "mmol/L",
}


def _canon_number(tok: str) -> str:
    folded = tok.translate(_OCR_TRANS).replace(",", ".")
    return folded


def _canon_unit(tok: str) -> str:
    key = tok.lower().translate(_OCR_TRANS).replace("1", "l")  # unit letters, not digits
    # e.g. 'mg/dl', 'g/dl', 'mmol/l'
    return _UNIT_CANON.get(key, tok)


def extract_rows(lines: list[str], ocr_text: str) -> list[LabRow]:
    rows: list[LabRow] = []
    seen: set[str] = set()
    for line in lines:
        test_name = None
        for key, canon in KNOWN_TESTS.items():
            if normalize(key) in normalize(line):
                test_name = canon
                break
        if not test_name or test_name in seen:
            continue
        m = _ROW_TAIL.search(line)
        if not m:
            # test present but numbers unreadable -> record unverified shell
            rows.append(LabRow(test=test_name, value=None, unit=None,
                               reference_range=None, flag=None, verified=False))
            seen.add(test_name)
            continue
        value = _canon_number(m.group("value"))
        unit = _canon_unit(m.group("unit"))
        low_ref = _canon_number(m.group("low"))
        high_ref = _canon_number(m.group("high"))
        flag = (m.group("flag") or "").upper() or None
        verified = grounded(value, ocr_text)
        rows.append(
            LabRow(
                test=test_name,
                value=value,
                unit=unit,
                reference_range=f"{low_ref}-{high_ref}",
                flag=flag,
                verified=verified,
            )
        )
        seen.add(test_name)
    return rows


def extract(ocr_text: str) -> Extraction:
    lines = [ln.strip() for ln in ocr_text.splitlines() if ln.strip()]
    name = extract_name(lines)
    mrn = extract_mrn(lines)
    date = extract_date(lines)
    return Extraction(
        name=Field(name, grounded(name, ocr_text) if name else False),
        mrn=Field(mrn, grounded(mrn, ocr_text) if mrn else False),
        date=Field(date, grounded(date, ocr_text) if date else False),
        rows=extract_rows(lines, ocr_text),
    )
