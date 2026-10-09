"""Universal input router: any ID, a device fingerprint, a name, a question or a
new-transaction JSON resolves to something ARGUS can investigate."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

import pandas as pd

from core import data

# Order matters: INV + 6 digits is an investigation, INV + 7 digits is an invoice.
PATTERNS: list[tuple[str, str]] = [
    ("alert", r"ALR\d{7}"), ("transaction", r"TXN\d{8}"), ("account", r"ACC\d{7}"), ("individual", r"IND\d{7}"),
    ("entity", r"ENT\d{6}"), ("supplier", r"SUP\d{6}"), ("device", r"DEV\d{7}"), ("fingerprint", r"fp_[0-9a-f]{12}"),
    ("invoice", r"INV\d{7}"), ("investigation", r"INV\d{6}"), ("kyc", r"KYC\d{6}"), ("watchlist", r"WL\d{6}"),
    ("ownership_link", r"OWN\d{7}"), ("rule", r"R\d{3}"),
]
_FULL = [(k, re.compile(rf"^\s*{p}\s*$", re.I)) for k, p in PATTERNS]
_ANY = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(p for _, p in PATTERNS) + r")(?![A-Za-z0-9_])", re.I)


@dataclass
class Route:
    kind: str                     # alert | ... | rule | name | question | new_txn | invalid
    value: str = ""
    ids: list[tuple[str, str]] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    payload: dict | None = None
    message: str = ""


def normalise_id(kind: str, raw: str) -> str:
    raw = raw.strip()
    return raw.lower() if kind == "fingerprint" else raw.upper()


def classify_id(token: str) -> str | None:
    for kind, rx in _FULL:
        if rx.match(token):
            return kind
    return None


def extract_ids(text: str) -> list[tuple[str, str]]:
    out, seen = [], set()
    for m in _ANY.finditer(text):
        tok = m.group(1)
        kind = classify_id(tok)
        if kind:
            val = normalise_id(kind, tok)
            if val not in seen:
                seen.add(val)
                out.append((kind, val))
    return out


def fuzzy_names(text: str, limit: int = 5, cutoff: int = 82) -> list[dict]:
    from rapidfuzz import fuzz, process

    names = _name_index()
    hits = process.extract(text.strip().lower(), names["key"].tolist(), scorer=fuzz.WRatio, limit=limit * 3, score_cutoff=cutoff)
    out, seen = [], set()
    for _key, score, idx in hits:
        row = names.iloc[idx]
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        out.append({"kind": row["kind"], "id": row["id"], "label": row["label"], "score": round(float(score), 1)})
        if len(out) >= limit:
            break
    return out


_NAMES: pd.DataFrame | None = None


def _name_index() -> pd.DataFrame:
    global _NAMES
    if _NAMES is None:
        ind = data.q("SELECT 'individual' AS kind, individual_id AS id, first_name || ' ' || last_name AS label FROM individuals")
        ent = data.q("SELECT 'entity' AS kind, entity_id AS id, legal_name AS label FROM business_entities")
        sup = data.q("SELECT 'supplier' AS kind, supplier_id AS id, supplier_name AS label FROM suppliers_clean WHERE supplier_name IS NOT NULL") \
            if data.has_table("suppliers_clean") else pd.DataFrame(columns=["kind", "id", "label"])
        df = pd.concat([ind, ent, sup], ignore_index=True).dropna(subset=["label"])
        df["key"] = df["label"].str.lower()
        _NAMES = df
    return _NAMES


def route(text: str) -> Route:
    raw = (text or "").strip()
    if not raw:
        return Route("invalid", message="Type an ID (e.g. ALR0005789), a device fingerprint, a name, or a question.")
    if len(raw) > 2000:
        return Route("invalid", message="Input is too long (2,000 characters max).")
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return Route("invalid", message="That looks like JSON but does not parse. Check quotes and commas.")
        if isinstance(payload, dict) and {"account_id", "amount"} <= set(payload):
            return Route("new_txn", payload=payload)
        return Route("invalid", message="Transaction JSON needs at least 'account_id' and 'amount'.")
    kind = classify_id(raw)
    if kind:
        return Route(kind, value=normalise_id(kind, raw))
    ids = extract_ids(raw)
    looks_like_question = "?" in raw or len(raw.split()) > 5 or bool(re.match(r"^(who|what|which|why|how|is|are|does|did|show|list|find)\b", raw, re.I))
    if ids and looks_like_question:
        return Route("question", value=raw, ids=ids)
    if ids:
        return Route(ids[0][0], value=ids[0][1], ids=ids)
    if re.fullmatch(r"[A-Za-z][A-Za-z .,'&-]{2,80}", raw) and not looks_like_question:
        cands = fuzzy_names(raw)
        if cands:
            return Route("name", value=raw, candidates=cands)
    if looks_like_question:
        cands = fuzzy_names(" ".join(w for w in re.findall(r"[A-Z][a-z]+", raw)), cutoff=88) if re.search(r"[A-Z][a-z]+ [A-Z][a-z]+", raw) else []
        if cands:
            return Route("question", value=raw, ids=[(c["kind"], c["id"]) for c in cands[:1]], candidates=cands)
        return Route("question", value=raw, message="No record IDs or known names found in the question.")
    return Route("invalid", message=f"No record matches '{raw[:60]}'. Try an ID such as ALR0005789, IND0057606, ENT000783, "
                                    "SUP000272, a fingerprint like fp_0e79cb1b294b, a name, or a question.")
