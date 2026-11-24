---
title: DocIntake Lite
emoji: 🧪
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

<!-- The YAML above is read by Hugging Face Spaces to build the Docker image. -->
<!-- It is harmless on GitHub (shown as a small metadata table). -->

# DocIntake Lite

A small prototype that turns **lab-report PDFs** (including noisy "scanned" ones)
into **grounded, validated FHIR Observations** and stores them in Postgres with
**per-clinic Row-Level Security** and **encrypted PHI**.

All data is **synthetic**.

```
PDF  ─▶  OCR (doctr, CPU)  ─▶  regex extract + grounding  ─▶  FHIR R4  ─▶  Postgres (RLS + encrypted PHI)
```

## What it does

- **OCR** – renders each PDF page with `pypdfium2` and reads it with
  [`python-doctr`](https://github.com/mindee/doctr) (pretrained weights from the
  Hugging Face hub, CPU). Returns text + per-word confidence.
- **Extraction** – rule/regex parsing of patient name, MRN, collection date and
  lab rows, tolerant of common OCR confusions (`O`/`0`, `l`/`1`).
- **Grounding** – every extracted value must appear in the OCR text after
  normalisation, or it is marked `verified: false`. A lab value is **never**
  stored as verified if it isn't in the text.
- **FHIR** – each lab row becomes a FHIR R4 `Observation` (LOINC code, UCUM
  unit, `H`/`L`/`N` interpretation, reference range), validated with
  `fhir.resources`.
- **Storage** – Postgres with pgcrypto-encrypted name/MRN and Row-Level
  Security isolating every clinic's data.
- **API** – FastAPI: upload a PDF, get back extracted fields (with verified
  flags) and the FHIR Observations.

## Architecture

```mermaid
flowchart LR
    U[Client] -->|POST /documents + X-Clinic-Id| API[FastAPI]
    API --> OCR[OCR: doctr + pypdfium2]
    OCR --> EX[Extract + ground]
    EX --> FH[FHIR R4 Observation<br/>validate]
    FH --> PIPE[Pipeline]
    PIPE -->|SET LOCAL app.clinic_id| DB[(Postgres)]

    subgraph DB_SEC [Postgres: security]
      P[patients<br/>name_enc, mrn_enc, mrn_hash]
      D[documents]
      O[observations<br/>fhir jsonb, verified]
      RLS{{RLS: clinic_id = app.clinic_id<br/>FORCE ROW LEVEL SECURITY}}
    end
    DB --- P
    DB --- D
    DB --- O
    P -.enforced by.- RLS
    O -.enforced by.- RLS

    U -->|GET /patients/:id/observations| API
```

## Security model

| Concern | Mechanism |
|---|---|
| **PHI at rest** | Patient name + MRN encrypted with pgcrypto `pgp_sym_encrypt`; key comes from `.env`, never stored in the DB. |
| **MRN lookup without decrypting** | `mrn_hash` = HMAC-SHA256 of the MRN (deterministic, so equality lookups work on ciphertext-adjacent data). |
| **Tenant isolation** | Row-Level Security on `patients`, `documents`, `observations`: `clinic_id = current_setting('app.clinic_id')::int`. Each request runs in a transaction with `SET LOCAL app.clinic_id`. |
| **No privilege escape** | The app connects as `app_user`, a role **without `BYPASSRLS`**. `FORCE ROW LEVEL SECURITY` is also set, so the policy applies even to a table owner (e.g. Neon's owner role, where a separate login role is restricted). |
| **No PHI in logs** | Encryption happens in SQL; API errors return only an exception type, never record contents. |
| **Grounding** | Values that aren't present in the OCR text are flagged unverified and never stored as verified — guards against OCR/extraction hallucination. |

## OCR accuracy

Measured by `scripts/eval.py` against `samples/truth.json`
(field = name, MRN, date, and each of 4 lab values per report):

<!-- EVAL_RESULTS -->
| Set | Reports | Field accuracy | OCR mean confidence |
|---|---|---|---|
| Clean (vector PDF)        | 2 | **100%** (14/14) | ~1.00 |
| Scanned (rotated + noise) | 2 | **100%** (14/14) | ~0.99 |
| **Overall**               | 4 | **100%** (28/28) | — |

Fields scored per report: patient name, MRN, date, and 4 lab values (HbA1c,
Glucose, Hemoglobin, Potassium). Every stored lab value was grounded in the OCR
text (4/4 rows verified per report). OCR engine: `python-doctr`
(`db_mobilenet_v3_large` + `crnn_mobilenet_v3_small`, CPU).

This is a small synthetic set of **printed** reports; 100% here reflects clean
synthetic generation, not real-world fax/scan quality (see Limitations).
<!-- /EVAL_RESULTS -->

## How to run

Reuses an existing Python venv that already has `torch` (doctr's backend).

```powershell
# 1. Install deps into the venv (torch already present)
uv pip install --python <venv>\Scripts\python.exe -r requirements.txt

# 2. Generate synthetic sample PDFs
python scripts/make_samples.py

# 3. Point .env at Postgres (Neon or local). A single Neon owner URL is enough:
#    DATABASE_URL=postgresql://USER:PASSWORD@ep-xxx.neon.tech/db?sslmode=require
python -m scripts.init_db       # creates extension, tables, RLS, seeds 2 clinics

# 4. Evaluate OCR accuracy
python scripts/eval.py

# 5. Run the API
uvicorn app.api:app --reload
#   POST /documents        (multipart file=@report.pdf, header X-Clinic-Id: 1)
#   GET  /patients/1/observations   (header X-Clinic-Id: 1)
#   GET  /health

# 6. Tests (DB tests auto-skip without DATABASE_URL)
pytest -q
```

Example upload:

```powershell
curl.exe -s -X POST http://127.0.0.1:8000/documents `
  -H "X-Clinic-Id: 1" -F "file=@samples/report_01_clean.pdf"
```

## Infrastructure

`infra/` holds Terraform for AWS — RDS Postgres (`storage_encrypted = true`,
`publicly_accessible = false`, private subnets) and an S3 document bucket
(SSE-KMS, public access blocked), with `staging`/`production` tfvars. It is
**validated, not applied** in this prototype:

```powershell
terraform -chdir=infra init -backend=false
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra validate
```

## Honest limitations

- **Prototype**, ~90 minutes of build. Not production-ready.
- Synthetic, **printed** lab reports with a fixed layout; the two "scanned"
  samples add rotation + noise but are still cleaner than real-world faxes.
- **Rule/regex** extraction over a known set of tests (HbA1c, Glucose,
  Hemoglobin, Potassium) — not a general document model.
- Terraform is **validated, not applied**; network (VPC/subnets) is assumed to
  exist and passed in as variables.
- **No auth, no UI**, single-page reports only, no de-duplication beyond
  `(clinic_id, mrn_hash)`, no audit trail.
- Encryption key lives in `.env` for the demo; real deployments should use a
  managed KMS/secret store.
```
