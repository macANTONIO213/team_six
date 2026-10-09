from core import router


def test_ids_route_to_record_types():
    cases = {
        "ALR0005789": "alert", "TXN00190688": "transaction", "ACC0051505": "account", "IND0057606": "individual",
        "ENT000783": "entity", "SUP000272": "supplier", "DEV0060659": "device", "fp_0e79cb1b294b": "fingerprint",
        "KYC010667": "kyc", "WL001493": "watchlist", "OWN0008019": "ownership_link", "R017": "rule",
    }
    for text, kind in cases.items():
        assert router.route(text).kind == kind, text


def test_investigation_vs_invoice():
    assert router.route("INV000001").kind == "investigation"
    assert router.route("INV0000001").kind == "invoice"


def test_case_and_whitespace_normalised():
    r = router.route("  alr0005789 ")
    assert (r.kind, r.value) == ("alert", "ALR0005789")
    assert router.route("FP_0E79CB1B294B").value == "fp_0e79cb1b294b"


def test_invalid_and_empty_inputs_are_friendly():
    for text in ("", "XYZ-123", "!!!", "x" * 3000):
        r = router.route(text)
        assert r.kind == "invalid" and r.message


def test_question_extracts_ids():
    r = router.route("Who shares a phone with IND0046429?")
    assert r.kind == "question" and r.ids == [("individual", "IND0046429")]


def test_new_transaction_json():
    r = router.route('{"account_id": "ACC0051505", "amount": 9850}')
    assert r.kind == "new_txn" and r.payload["amount"] == 9850
    assert router.route('{"amount": 1}').kind == "invalid"
    assert router.route("{not json").kind == "invalid"
