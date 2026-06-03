"""V5.8/V6-prep Company & Fundamentals Research Layer driver (read-only).

Builds the SEC EDGAR company research bundle for a ticker (default AAPL,
2019-2024) and writes reports under reports/company/sec_edgar/.

RESEARCH ONLY. No broker / live / IBKR. No options/ThetaData. No trading
signal. No backtest/strategy change. LIVE_TRADING_ENABLED stays False.

SEC asks for a descriptive User-Agent with contact info; set it via:
    set QUANTBOT_SEC_USER_AGENT=Your Name your-email@example.com   (Windows)
The value is never printed or cached by this code. If unset, a neutral
placeholder is used and live fetching may be refused by SEC -- the run then
degrades to cache/empty and still writes an availability report.

Usage:
    python scripts/run_company_research.py            # AAPL 2019-2024
    python scripts/run_company_research.py MSFT 2020-01-01 2024-12-31
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import quantbot
from quantbot.company.company_report import build_company_research


def main(argv: list[str]) -> int:
    assert quantbot.LIVE_TRADING_ENABLED is False, "Research only."
    ticker = argv[1] if len(argv) > 1 else "AAPL"
    start = argv[2] if len(argv) > 2 else "2019-01-01"
    end = argv[3] if len(argv) > 3 else "2024-12-31"

    print(f"Company research: {ticker}  {start} -> {end}  (read-only, SEC EDGAR)")
    summary = build_company_research(ticker, start=start, end=end)

    print("\n=== Summary ===")
    for k, v in summary.items():
        if k == "reports":
            continue
        print(f"  {k:28s}: {v}")
    print("\n=== Reports written ===")
    for name, path in summary["reports"].items():
        print(f"  {name:28s}: {path}")
    if not summary["online_submissions"]:
        print("\nNOTE: SEC submissions were not reachable this run (offline or no "
              "cache). Reports reflect cache/empty state. Set "
              "QUANTBOT_SEC_USER_AGENT and re-run with network to populate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
