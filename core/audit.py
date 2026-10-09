"""SQLite store for human decisions, the audit trail, LLM call logs (DATA-05) and the LLM response cache."""
from __future__ import annotations

import json
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

import pandas as pd

from core import config

_lock = threading.Lock()
_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_calls (
    call_id TEXT PRIMARY KEY, ts TEXT, page TEXT, subject TEXT, kind TEXT, model TEXT, prompt_hash TEXT,
    input_tokens INTEGER, output_tokens INTEGER, latency_ms INTEGER, status TEXT, guardrail TEXT, error TEXT, cached INTEGER);
CREATE TABLE IF NOT EXISTS llm_cache (prompt_hash TEXT PRIMARY KEY, ts TEXT, model TEXT, response TEXT);
CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY, ts TEXT, analyst TEXT, subject_type TEXT, subject_id TEXT, lane TEXT,
    ai_risk_level TEXT, ai_recommendation TEXT, ai_confidence REAL, human_disposition TEXT, rationale TEXT,
    consolidated_alerts TEXT, n_consolidated INTEGER, requires_second_approver INTEGER, second_approver TEXT,
    status TEXT, citation_status TEXT, llm_call_id TEXT, override INTEGER);
CREATE TABLE IF NOT EXISTS audit_log (event_id TEXT PRIMARY KEY, ts TEXT, actor TEXT, action TEXT, subject TEXT, detail TEXT);
"""


@contextmanager
def _db():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        con = sqlite3.connect(config.DB_PATH, timeout=10)
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_SCHEMA)
            yield con
            con.commit()
        finally:
            con.close()


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def new_id(prefix: str) -> str:
    return f"{prefix}-{time.strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"


def log_event(actor: str, action: str, subject: str, detail: dict | str | None = None) -> str:
    eid = new_id("EVT")
    with _db() as con:
        con.execute("INSERT INTO audit_log VALUES (?,?,?,?,?,?)",
                    (eid, _now(), actor or "unknown", action, subject, json.dumps(detail, default=str) if not isinstance(detail, str) else detail))
    return eid


def log_llm_call(**kw) -> str:
    cid = kw.get("call_id") or new_id("LLM")
    cols = ["call_id", "ts", "page", "subject", "kind", "model", "prompt_hash", "input_tokens", "output_tokens",
            "latency_ms", "status", "guardrail", "error", "cached"]
    row = {"call_id": cid, "ts": _now(), **kw}
    with _db() as con:
        con.execute(f"INSERT OR REPLACE INTO llm_calls ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                    [row.get(c) for c in cols])
    return cid


def update_llm_guardrail(call_id: str, guardrail: str) -> None:
    with _db() as con:
        con.execute("UPDATE llm_calls SET guardrail = ? WHERE call_id = ?", (guardrail, call_id))


def cache_get(prompt_hash: str) -> dict | None:
    with _db() as con:
        row = con.execute("SELECT response FROM llm_cache WHERE prompt_hash = ?", (prompt_hash,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(prompt_hash: str, model: str, response: dict) -> None:
    with _db() as con:
        con.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?,?)", (prompt_hash, _now(), model, json.dumps(response)))


def calls_today() -> int:
    with _db() as con:
        return con.execute("SELECT count(*) FROM llm_calls WHERE cached = 0 AND ts >= ?", (time.strftime("%Y-%m-%d"),)).fetchone()[0]


SECOND_APPROVAL_ACTIONS = ("Refer to MLRO (SAR-like)", "Hold supplier payments pending review")


def save_decision(*, analyst: str, subject_type: str, subject_id: str, lane: str | None, case: dict | None,
                  disposition: str, rationale: str, consolidated: list[str] | None, second_approver: str | None,
                  citation_status: str | None, llm_call_id: str | None) -> dict:
    needs_second = disposition in SECOND_APPROVAL_ACTIONS
    second = (second_approver or "").strip() or None
    if needs_second and second and second.lower() == (analyst or "").strip().lower():
        raise ValueError("The second approver must be a different person from the analyst.")
    status = "Final" if not needs_second else ("Final (two approvers)" if second else "Pending second approval")
    ai_rec = (case or {}).get("recommended_action")
    rec = {
        "decision_id": new_id("DEC"), "ts": _now(), "analyst": analyst, "subject_type": subject_type, "subject_id": subject_id,
        "lane": lane, "ai_risk_level": (case or {}).get("risk_level"), "ai_recommendation": ai_rec,
        "ai_confidence": (case or {}).get("confidence"), "human_disposition": disposition, "rationale": rationale,
        "consolidated_alerts": json.dumps(consolidated or []), "n_consolidated": len(consolidated or []),
        "requires_second_approver": int(needs_second), "second_approver": second, "status": status,
        "citation_status": citation_status, "llm_call_id": llm_call_id,
        "override": int(bool(ai_rec) and ai_rec != disposition),
    }
    with _db() as con:
        con.execute(f"INSERT INTO decisions ({','.join(rec)}) VALUES ({','.join('?' * len(rec))})", list(rec.values()))
    log_event(analyst, "decision", subject_id, {k: rec[k] for k in ("decision_id", "human_disposition", "ai_recommendation", "status", "n_consolidated")})
    return rec


def approve_pending(decision_id: str, approver: str) -> str:
    with _db() as con:
        row = con.execute("SELECT analyst, status FROM decisions WHERE decision_id = ?", (decision_id,)).fetchone()
        if not row:
            raise ValueError("Decision not found")
        if row[1] != "Pending second approval":
            raise ValueError(f"Decision is '{row[1]}', not pending")
        if row[0].strip().lower() == approver.strip().lower():
            raise ValueError("The second approver must be a different person from the analyst.")
        con.execute("UPDATE decisions SET second_approver = ?, status = 'Final (two approvers)' WHERE decision_id = ?", (approver, decision_id))
    log_event(approver, "second_approval", decision_id, None)
    return "Final (two approvers)"


def frame(table: str, limit: int = 500) -> pd.DataFrame:
    if table not in {"decisions", "audit_log", "llm_calls"}:
        raise ValueError(table)
    with _db() as con:
        return pd.read_sql_query(f"SELECT * FROM {table} ORDER BY ts DESC LIMIT {int(limit)}", con)
