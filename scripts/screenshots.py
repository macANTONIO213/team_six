"""Capture full-page screenshots of every ARGUS page (visual QA).

    python -m scripts.screenshots [base_url] [out_dir] [page ...]
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8502"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "shots")
ONLY = set(sys.argv[3:])
PAGES = [
    ("overview", ""), ("triage", "Triage_Queue"), ("investigate", "Investigate"), ("score", "Score_Transaction"),
    ("rules", "Rule_Studio"), ("supplier", "Supplier_360"), ("impact", "Impact_Governance"), ("help", "Help"),
]


def wait_ready(page) -> None:
    page.wait_for_selector("[data-testid='stApp']", timeout=60000)
    for _ in range(120):
        if page.locator("[data-testid='stStatusWidget']").count() == 0:
            break
        time.sleep(0.5)
    time.sleep(float(__import__("os").environ.get("SHOT_WAIT", "5")))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": int(__import__("os").environ.get("SHOT_H", "2400"))})
        for name, path in PAGES:
            if ONLY and name not in ONLY:
                continue
            pg.goto(f"{BASE}/{path}", wait_until="networkidle")
            wait_ready(pg)
            if name == "investigate":
                box = pg.get_by_label("Search")
                if box.count():
                    box.first.fill("ALR0005789")
                    box.first.press("Enter")
                    wait_ready(pg)
            pg.screenshot(path=str(OUT / f"{name}.png"), full_page=True)
            print("saved", OUT / f"{name}.png", flush=True)
        b.close()


if __name__ == "__main__":
    main()
