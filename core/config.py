"""Runtime configuration: environment variables with local defaults.

Nothing secret lives here. On EC2 the values come from /opt/argus/argus.env and
AWS credentials come from the instance role (no API keys anywhere).
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    if os.environ.get("ARGUS_DATA_DIR"):
        return Path(os.environ["ARGUS_DATA_DIR"])
    for candidate in (REPO_ROOT / "data", REPO_ROOT.parent / "center_data"):
        if (candidate / "D_risk").exists():
            return candidate
    return REPO_ROOT / "data"


DATA_DIR = _data_dir()
RISK_DIR = DATA_DIR / "D_risk"
RAW_DIR = DATA_DIR / "raw"
CACHE_DIR = Path(os.environ.get("ARGUS_CACHE_DIR", REPO_ROOT / "cache"))
DB_PATH = Path(os.environ.get("ARGUS_DB_PATH", REPO_ROOT / "argus.db"))

# LLM: Amazon Bedrock (Claude) through Australia-only inference profiles.
LLM_PROVIDER = os.environ.get("ARGUS_LLM_PROVIDER", "bedrock")  # bedrock | template
LLM_MODEL = os.environ.get("ARGUS_LLM_MODEL", "au.anthropic.claude-sonnet-4-6")
LLM_FAST_MODEL = os.environ.get("ARGUS_LLM_FAST_MODEL", "au.anthropic.claude-haiku-4-5-20251001-v1:0")
AWS_REGION = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-southeast-2"
LLM_TIMEOUT_S = int(os.environ.get("ARGUS_LLM_TIMEOUT_S", "60"))
LLM_TEMPERATURE = float(os.environ.get("ARGUS_LLM_TEMPERATURE", "0.2"))
LLM_MAX_TOKENS = int(os.environ.get("ARGUS_LLM_MAX_TOKENS", "3000"))
# Cost guard for a public demo URL.
LLM_MAX_CALLS_PER_SESSION = int(os.environ.get("ARGUS_LLM_MAX_CALLS_PER_SESSION", "40"))
LLM_MAX_CALLS_PER_DAY = int(os.environ.get("ARGUS_LLM_MAX_CALLS_PER_DAY", "800"))

# Optional shared access code for the hosted demo (empty = open).
ACCESS_CODE = os.environ.get("ARGUS_ACCESS_CODE", "")

AS_OF = "2026-09-30"
TRAIN_CUTOFF = "2026-01-01"  # out-of-time backtest: train < cutoff, test >= cutoff
NOISE_RULES = ("R017", "R023")
RING_MIN_SIZE = 5  # identity clusters at or above this size are treated as networks
