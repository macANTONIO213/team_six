from core import guardrails


def test_minimise_drops_names_demographics_and_staff_ids():
    ev = {"subject": {"id": "IND0057606", "first_name": "Cameron", "nationality": "X", "gender": "M", "occupation": "Student"},
          "alerts": [{"alert_id": "ALR0005789", "analyst_employee_id": "EMP000123", "note": "handled by EMP004567"}],
          "entity": {"entity_id": "ENT000783", "legal_name": "Kelix Systems Ltd."}}
    out = guardrails.minimise(ev)
    flat = str(out)
    for banned in ("Cameron", "nationality", "gender", "occupation", "EMP000123", "EMP004567", "Kelix"):
        assert banned not in flat
    assert "IND0057606" in flat and "ALR0005789" in flat and "[staff]" in flat


def test_citation_check_verified_and_unverified():
    known = {"IND0057606", "ALR0005789", "fp_0e79cb1b294b", "3ee5f74bbbad048b"}
    ok = guardrails.check_citations({"narrative": "Shared device [fp_0e79cb1b294b] and phone [3ee5f74bbbad048b] link [IND0057606]."}, known)
    assert ok["status"] == "verified" and ok["unknown"] == []
    bad = guardrails.check_citations({"narrative": "See [TXN00000001] and [IND0057606]."}, known)
    assert bad["status"] == "unverified" and bad["unknown"] == ["TXN00000001"]
    none = guardrails.check_citations({"narrative": "No IDs here."}, known)
    assert none["status"] == "uncited"


def test_id_regex_distinguishes_formats():
    ids = guardrails.extract_ids("INV000001 INV0000001 SUP000272 R017 xACC0051505 ACC0049415")
    assert {"INV000001", "INV0000001", "SUP000272", "R017", "ACC0049415"} <= ids
    assert "ACC0051505" not in ids, "IDs glued to other characters are not matched"
