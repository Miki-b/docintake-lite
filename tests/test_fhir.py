from app.fhir import build_observation, validate_observation


def test_observation_validates_and_has_loinc():
    obs = build_observation("HbA1c", "7.8", "%", "4.0-5.6", "H")
    res = validate_observation(obs)
    assert res.__resource_type__ == "Observation"
    assert res.status == "final"
    assert res.code.coding[0].system == "http://loinc.org"
    assert res.code.coding[0].code == "4548-4"
    assert float(res.valueQuantity.value) == 7.8
    assert res.valueQuantity.code == "%"
    assert res.interpretation[0].coding[0].code == "H"
    assert float(res.referenceRange[0].low.value) == 4.0
    assert float(res.referenceRange[0].high.value) == 5.6


def test_each_known_test_maps_to_expected_loinc():
    expected = {
        "HbA1c": "4548-4",
        "Glucose": "2345-7",
        "Hemoglobin": "718-7",
        "Potassium": "2823-3",
    }
    for test, code in expected.items():
        obs = build_observation(test, "1.0", "%")
        res = validate_observation(obs)
        assert res.code.coding[0].code == code
