-- DocIntake Lite schema: encrypted PHI + Row-Level Security by clinic.
-- Run as a superuser/owner (ADMIN_DATABASE_URL). Idempotent.
--
-- Security model:
--   * Patient name + MRN are encrypted at rest with pgcrypto pgp_sym_encrypt
--     using a key supplied by the app at query time (never stored in the DB).
--   * mrn_hash is an HMAC of the MRN for equality lookups without decrypting.
--   * RLS restricts every row to its clinic. The app connects as app_user,
--     which does NOT have BYPASSRLS. FORCE ROW LEVEL SECURITY is also set so
--     the policy applies even to a table owner (e.g. Neon's owner role, where
--     creating a separate NOBYPASSRLS login role is restricted).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Application role: login, NO BYPASSRLS. Guarded so re-runs don't fail.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user LOGIN PASSWORD 'app_user' NOBYPASSRLS;
  END IF;
END
$$;

CREATE TABLE IF NOT EXISTS clinics (
  id          serial PRIMARY KEY,
  name        text NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
  id          serial PRIMARY KEY,
  clinic_id   int NOT NULL REFERENCES clinics(id),
  name_enc    bytea NOT NULL,          -- pgp_sym_encrypt(name, key)
  mrn_enc     bytea NOT NULL,          -- pgp_sym_encrypt(mrn, key)
  mrn_hash    bytea NOT NULL,          -- hmac(mrn, hmac_key, 'sha256')
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (clinic_id, mrn_hash)
);

CREATE TABLE IF NOT EXISTS documents (
  id          serial PRIMARY KEY,
  clinic_id   int NOT NULL REFERENCES clinics(id),
  patient_id  int REFERENCES patients(id),
  filename    text,
  ocr_engine  text,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS observations (
  id          serial PRIMARY KEY,
  clinic_id   int NOT NULL REFERENCES clinics(id),
  patient_id  int NOT NULL REFERENCES patients(id),
  document_id int REFERENCES documents(id),
  fhir        jsonb NOT NULL,
  verified    boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- ---- Row-Level Security --------------------------------------------------
-- Policy: a row is visible/writable only when its clinic_id matches the
-- per-transaction GUC app.clinic_id (set via SET LOCAL). Unset -> NULL -> no
-- rows (fail closed).

ALTER TABLE patients     ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents    ENABLE ROW LEVEL SECURITY;
ALTER TABLE observations ENABLE ROW LEVEL SECURITY;

ALTER TABLE patients     FORCE ROW LEVEL SECURITY;
ALTER TABLE documents    FORCE ROW LEVEL SECURITY;
ALTER TABLE observations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS clinic_isolation ON patients;
CREATE POLICY clinic_isolation ON patients
  USING (clinic_id = NULLIF(current_setting('app.clinic_id', true), '')::int)
  WITH CHECK (clinic_id = NULLIF(current_setting('app.clinic_id', true), '')::int);

DROP POLICY IF EXISTS clinic_isolation ON documents;
CREATE POLICY clinic_isolation ON documents
  USING (clinic_id = NULLIF(current_setting('app.clinic_id', true), '')::int)
  WITH CHECK (clinic_id = NULLIF(current_setting('app.clinic_id', true), '')::int);

DROP POLICY IF EXISTS clinic_isolation ON observations;
CREATE POLICY clinic_isolation ON observations
  USING (clinic_id = NULLIF(current_setting('app.clinic_id', true), '')::int)
  WITH CHECK (clinic_id = NULLIF(current_setting('app.clinic_id', true), '')::int);

-- Privileges for the app role (RLS still applies on top of these grants).
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO app_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE ON TABLES TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO app_user;

-- ---- Seed two clinics ----------------------------------------------------
INSERT INTO clinics (id, name)
VALUES (1, 'Valley Regional Clinic'), (2, 'Lakeside Family Health')
ON CONFLICT (id) DO NOTHING;
SELECT setval('clinics_id_seq', (SELECT max(id) FROM clinics));
