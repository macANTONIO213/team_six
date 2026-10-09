"""Data access: read-only DuckDB views over the REPH risk parquet, the derived
cache tables, and cleaning of the dirty raw finance files.

DuckDB connections are not safe to share across Streamlit's session threads, so
every query runs on its own cursor of one shared in-memory database.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

import duckdb
import pandas as pd

from core import config

_lock = threading.Lock()
_con: duckdb.DuckDBPyConnection | None = None


def _register(con: duckdb.DuckDBPyConnection) -> None:
    for folder in (config.RISK_DIR, config.CACHE_DIR):
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*.parquet")):
            name = path.stem
            if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
                continue
            posix = path.resolve().as_posix().replace("'", "''")
            con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{posix}')")


def connection() -> duckdb.DuckDBPyConnection:
    global _con
    with _lock:
        if _con is None:
            if not config.RISK_DIR.exists():
                raise FileNotFoundError(
                    f"REPH risk data not found at {config.RISK_DIR}. Set ARGUS_DATA_DIR to the folder holding D_risk/ and raw/."
                )
            con = duckdb.connect(database=":memory:")
            con.execute("SET threads TO 4")
            _register(con)
            _con = con
        return _con


def refresh_views() -> None:
    """Re-register views (call after precompute writes new cache files)."""
    with _lock:
        if _con is not None:
            _register(_con)


def q(sql: str, params: list | tuple | None = None) -> pd.DataFrame:
    cur = connection().cursor()
    try:
        return cur.execute(sql, params or []).df()
    finally:
        cur.close()


def scalar(sql: str, params: list | tuple | None = None):
    cur = connection().cursor()
    try:
        row = cur.execute(sql, params or []).fetchone()
        return None if row is None else row[0]
    finally:
        cur.close()


def has_table(name: str) -> bool:
    return bool(scalar("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [name]))


# --------------------------------------------------------------------------- raw cleaning
_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%b %d, %Y %H:%M:%S", "%b %d, %Y")


def parse_mixed_dates(values: pd.Series) -> pd.Series:
    """Parse ISO, DD/MM/YYYY and 'Mon DD, YYYY' strings (the three formats in raw/)."""
    s = values.astype("string").str.strip()
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    for fmt in _FORMATS:
        todo = out.isna() & s.notna() & (s != "")
        if not todo.any():
            break
        out.loc[todo] = pd.to_datetime(s[todo], format=fmt, errors="coerce")
    return out


def _norm_id(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.upper()


def load_raw_suppliers() -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(config.RAW_DIR / "suppliers_raw.csv", dtype=str, keep_default_na=False, na_values=[""])
    stats = {"rows_raw": len(raw)}
    raw["supplier_id"] = _norm_id(raw["supplier_id"])
    raw["entity_id"] = _norm_id(raw["entity_id"])
    df = raw.drop_duplicates(subset="supplier_id", keep="first").copy()
    stats["near_duplicates_dropped"] = stats["rows_raw"] - len(df)
    df["supplier_name"] = df["supplier_name"].astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    df["onboarded_date"] = parse_mixed_dates(df["onboarded_date"])
    stats["onboarded_date_unparsed"] = int(df["onboarded_date"].isna().sum())
    for col in ("risk_tier", "category", "status", "country"):
        df[col] = df[col].astype("string").str.strip()
    df["payment_terms_days"] = pd.to_numeric(df["payment_terms_days"], errors="coerce")
    stats["rows_clean"] = len(df)
    return df.drop(columns=["_ingested_at"], errors="ignore"), stats


def load_raw_invoices(supplier_ids: set[str] | None = None) -> tuple[pd.DataFrame, dict]:
    raw = pd.read_csv(config.RAW_DIR / "invoices_raw.csv", dtype=str, keep_default_na=False, na_values=[""])
    stats = {"rows_raw": len(raw)}
    raw["invoice_id"] = _norm_id(raw["invoice_id"])
    raw["supplier_id"] = _norm_id(raw["supplier_id"])
    df = raw.drop_duplicates(subset="invoice_id", keep="first").copy()
    stats["near_duplicates_dropped"] = stats["rows_raw"] - len(df)
    df["received_at"] = parse_mixed_dates(df["received_at"])
    df["invoice_date"] = parse_mixed_dates(df["invoice_date"])
    df["due_date"] = parse_mixed_dates(df["due_date"])
    stats["received_at_unparsed"] = int(df["received_at"].isna().sum())
    channel = df["channel"].astype("string").str.strip().str.lower().str.replace(r"\s+", " ", regex=True)
    df["channel"] = channel.map({"edi": "EDI", "email": "Email", "supplier portal": "Supplier portal"}).fillna(channel)
    df["status"] = df["status"].astype("string").str.strip()
    for col in ("net_amount", "tax_amount", "gross_amount", "amount_usd"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    if supplier_ids is not None:
        df["orphan_supplier"] = ~df["supplier_id"].isin(supplier_ids)
        stats["orphan_supplier_invoices"] = int(df["orphan_supplier"].sum())
    stats["rows_clean"] = len(df)
    return df.drop(columns=["_ingested_at"], errors="ignore"), stats


def cache_path(name: str) -> Path:
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return config.CACHE_DIR / name
