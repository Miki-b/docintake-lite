"""Postgres-backed tests: encryption round-trip + RLS isolation.
Skipped automatically when no DATABASE_URL is reachable.
"""
from app import db
from tests.conftest import requires_db

_OBS = {"resourceType": "Observation", "status": "final", "code": {"text": "HbA1c"}}


@requires_db
def test_encryption_roundtrip(clean_db):
    with db.clinic_session(1) as cur:
        pid = db.upsert_patient(cur, 1, "Maria Gonzalez", "0048715")
    with db.clinic_session(1) as cur:
        dec = db.decrypt_patient(cur, pid)
    assert dec == {"name": "Maria Gonzalez", "mrn": "0048715"}


@requires_db
def test_ciphertext_is_not_plaintext(clean_db):
    with db.clinic_session(1) as cur:
        pid = db.upsert_patient(cur, 1, "Secret Name", "9999999")
        # Read the raw stored bytes (within clinic context so it works under
        # FORCE RLS, e.g. on Neon's owner role, not only a superuser).
        cur.execute("SELECT name_enc, mrn_enc FROM patients WHERE id=%s", [pid])
        name_enc, mrn_enc = cur.fetchone()
    assert b"Secret Name" not in bytes(name_enc)
    assert b"9999999" not in bytes(mrn_enc)


@requires_db
def test_rls_blocks_other_clinic(clean_db):
    with db.clinic_session(1) as cur:
        pid = db.upsert_patient(cur, 1, "Alice Example", "1112223")
        did = db.insert_document(cur, 1, pid, "f.pdf", "mock")
        db.insert_observation(cur, 1, pid, did, _OBS, True)

    # Clinic 1 sees its own observation.
    with db.clinic_session(1) as cur:
        assert len(db.fetch_observations(cur, pid)) == 1

    # Clinic 2 sees nothing for the same patient id.
    with db.clinic_session(2) as cur:
        assert db.fetch_observations(cur, pid) == []
        # The patient row itself is invisible to clinic 2.
        assert db.decrypt_patient(cur, pid) is None
