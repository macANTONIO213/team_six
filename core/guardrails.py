"""LLM guardrails: data minimisation before a prompt leaves the app, and a
citation check on everything that comes back."""
from __future__ import annotations

import json
import re
from typing import Any

# Every record-ID format in the REPH risk/finance data, plus device fingerprints and 16-hex attribute hashes.
ID_REGEX = re.compile(
    r"(?<![A-Za-z0-9_])("
    r"ALR\d{7}|TXN\d{8}|ACC\d{7}|IND\d{7}|ENT\d{6}|SUP\d{6}|DEV\d{7}|INV\d{6,7}|KYC\d{6}|WL\d{6}|OWN\d{7}"
    r"|ADR\d{7}|IDA\d{8}|CUS\d{6}|PO\d{7}|CL\d{5}|R0\d{2}|fp_[0-9a-f]{12}|[0-9a-f]{16}"
    r")(?![A-Za-z0-9_])"
)

# Keys never sent to the LLM (names, demographics, staff identifiers, free-text addresses).
FORBIDDEN_KEYS = {
    "first_name", "last_name", "full_name", "name", "legal_name", "supplier_name", "customer_name",
    "date_of_birth", "dob", "age", "nationality", "gender", "occupation", "email",
    "address_line", "postal_code", "registration_number",
    "analyst_employee_id", "lead_analyst_employee_id", "processor_employee_id", "employee_id",
    "resolver_employee_id", "account_manager_employee_id",
}
_EMP = re.compile(r"\bEMP\d{6}\b")


def minimise(obj: Any) -> Any:
    """Recursively drop forbidden keys and mask any employee IDs that slipped into values."""
    if isinstance(obj, dict):
        return {k: minimise(v) for k, v in obj.items() if k not in FORBIDDEN_KEYS}
    if isinstance(obj, list):
        return [minimise(v) for v in obj]
    if isinstance(obj, str):
        return _EMP.sub("[staff]", obj)
    return obj


def extract_ids(obj: Any) -> set[str]:
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    return set(ID_REGEX.findall(text))


def check_citations(output: dict, evidence_ids: set[str]) -> dict:
    """Every ID the model mentions must exist in the evidence it was given."""
    cited = extract_ids(output)
    unknown = sorted(cited - evidence_ids)
    narrative_ids = extract_ids(output.get("narrative", "") or output.get("answer", "") or "")
    if unknown:
        status = "unverified"
    elif not narrative_ids:
        status = "uncited"
    else:
        status = "verified"
    return {"status": status, "cited": sorted(cited), "unknown": unknown, "n_cited": len(cited)}
