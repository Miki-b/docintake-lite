from app.extract import extract, grounded, normalize


def test_grounded_accepts_present_value():
    text = "Patient: Jane Doe\nMRN: 0012345\nHbA1c 7.8 % 4.0-5.6 H"
    assert grounded("7.8", text)
    assert grounded("Jane Doe", text)


def test_grounded_rejects_absent_value():
    text = "Patient: Jane Doe\nHbA1c 7.8 % 4.0-5.6 H"
    assert not grounded("9.9", text)  # fabricated value not in text


def test_normalize_tolerates_ocr_confusions():
    # O/0 and l/1 fold to the same canonical form.
    assert normalize("MRN O0l2") == normalize("mrn 0012")


def test_extract_marks_rows_verified_only_when_grounded():
    text = "Patient: Ann Lee\nMRN: 5550001\nGlucose 142 mg/dL 70-99 H"
    ex = extract(text)
    row = next(r for r in ex.rows if r.test == "Glucose")
    assert row.value == "142"
    assert row.verified is True


def test_pipeline_grounding_rejects_hallucinated_value():
    # Simulate an extraction value that is NOT in the OCR text: grounded() is
    # the gate the pipeline uses, so it must return False.
    ocr_text = "Potassium reading unreadable on this scan"
    assert grounded("4.4", ocr_text) is False
