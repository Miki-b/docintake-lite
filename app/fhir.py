"""Map extracted lab rows to FHIR R4 Observation resources and validate them
with fhir.resources (R4B Observation model).
"""
from __future__ import annotations

import re

from fhir.resources.R4B.observation import Observation

LOINC_SYSTEM = "http://loinc.org"
UCUM_SYSTEM = "http://unitsofmeasure.org"
INTERP_SYSTEM = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"

# Canonical test name -> (LOINC code, display).
LOINC = {
    "HbA1c": ("4548-4", "Hemoglobin A1c/Hemoglobin.total in Blood"),
    "Glucose": ("2345-7", "Glucose [Mass/volume] in Serum or Plasma"),
    "Hemoglobin": ("718-7", "Hemoglobin [Mass/volume] in Blood"),
    "Potassium": ("2823-3", "Potassium [Moles/volume] in Serum or Plasma"),
}

# Display unit -> UCUM code (here they coincide, but keep the mapping explicit).
UCUM = {
    "%": "%",
    "mg/dL": "mg/dL",
    "g/dL": "g/dL",
    "mmol/L": "mmol/L",
}

INTERP = {
    "H": ("H", "High"),
    "L": ("L", "Low"),
    "N": ("N", "Normal"),
}


def _quantity(value: str, unit: str | None) -> dict:
    q: dict = {"value": float(value)}
    if unit:
        q["unit"] = unit
        ucum = UCUM.get(unit)
        if ucum:
            q["system"] = UCUM_SYSTEM
            q["code"] = ucum
    return q


def _parse_range(reference_range: str | None) -> tuple[str, str] | None:
    if not reference_range:
        return None
    m = re.match(r"\s*([0-9.]+)\s*-\s*([0-9.]+)\s*$", reference_range)
    if not m:
        return None
    return m.group(1), m.group(2)


def build_observation(
    test: str,
    value: str,
    unit: str | None = None,
    reference_range: str | None = None,
    flag: str | None = None,
    subject_ref: str | None = None,
) -> dict:
    """Build a FHIR R4 Observation dict for one lab row. Unknown tests still
    produce a valid Observation using a text-only code."""
    loinc = LOINC.get(test)
    if loinc:
        code = {"coding": [{"system": LOINC_SYSTEM, "code": loinc[0], "display": loinc[1]}],
                "text": test}
    else:
        code = {"text": test}

    obs: dict = {
        "resourceType": "Observation",
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                        "code": "laboratory",
                        "display": "Laboratory",
                    }
                ]
            }
        ],
        "code": code,
        "valueQuantity": _quantity(value, unit),
    }
    if subject_ref:
        obs["subject"] = {"reference": subject_ref}

    if flag and flag in INTERP:
        c, display = INTERP[flag]
        obs["interpretation"] = [
            {"coding": [{"system": INTERP_SYSTEM, "code": c, "display": display}]}
        ]

    rng = _parse_range(reference_range)
    if rng:
        low, high = rng
        rr: dict = {
            "low": _quantity(low, unit),
            "high": _quantity(high, unit),
        }
        obs["referenceRange"] = [rr]
    return obs


def validate_observation(obs: dict) -> Observation:
    """Validate a dict against the FHIR R4B Observation model. Raises on invalid."""
    return Observation.model_validate(obs)
