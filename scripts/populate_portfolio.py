"""V7.1 — Portfolio CSV data-population helper (manual entries only).

Append one validated row to either:

  * ``data/portfolio/positions.csv``      (subcommand: ``add-position``)
  * ``data/portfolio/transactions.csv``   (subcommand: ``add-transaction``)

The script does NOT:
  * connect to a broker / send an order
  * fetch from the network — no macro feed, no equity feed, no broker API
  * scrape news / web pages
  * mutate any V6 sector / V7.8 marketpulse artefact
  * touch any live options data feed
  * affect ``LIVE_TRADING_ENABLED`` (stays ``False``)

It DOES:
  * validate every row via the V7.1 dataclasses + a few extra non-empty
    CLI-level checks
  * APPEND one row in append-mode with explicit
    ``idempotent | append | strict`` modes
  * create the CSV with a header on first run

Manual entry examples:

    # One position snapshot
    python scripts/populate_portfolio.py add-position \\
        --as-of 2026-06-03 --account MAIN --ticker NVDA \\
        --company-name "NVIDIA Corp" --asset-type STOCK \\
        --quantity 100 --average-cost 450.00 --last-price 510.00 \\
        --market-value 51000.00 --unrealized-pnl 6000.00 \\
        --sector SEMICONDUCTOR --theme "AI accelerator" --source MANUAL

    # One trade
    python scripts/populate_portfolio.py add-transaction \\
        --date 2026-06-03 --account MAIN --ticker NVDA \\
        --side BUY --quantity 100 --price 450.00 --fees 1.00 \\
        --reason "thesis BULL on AI accelerator demand" \\
        --linked-thesis "SEMI-NVDA-REV-T1" --source MANUAL

``quantbot.LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import quantbot
from quantbot.research.portfolio import (
    ALLOWED_ASSET_TYPE,
    ALLOWED_TRANSACTION_SIDE,
    DEFAULT_POSITIONS_FILE,
    DEFAULT_TRANSACTIONS_FILE,
    PortfolioSchemaError,
    PositionRow,
    TransactionRow,
    append_position_rows,
    append_transaction_rows,
    ensure_positions_header,
    ensure_transactions_header,
)


class PopulatePortfolioValidationError(ValueError):
    """Raised when an operator-supplied row fails CLI-level checks beyond
    the V7.1 dataclass schema (e.g. empty as_of / account / ticker)."""


def _require_non_empty(value: str, name: str) -> None:
    if not value or not value.strip():
        raise PopulatePortfolioValidationError(
            f"{name} must be non-empty"
        )


# --------------------------------------------------------------------------- #
# Python entry points (testable without argparse)
# --------------------------------------------------------------------------- #
def add_position_row(
    *,
    as_of: str,
    account: str,
    ticker: str,
    company_name: str = "",
    asset_type: str = "N_A",
    quantity: str = "",
    average_cost: str = "",
    last_price: str = "",
    market_value: str = "",
    unrealized_pnl: str = "",
    realized_pnl: str = "",
    currency: str = "USD",
    sector: str = "",
    theme: str = "",
    source: str = "",
    notes: str = "",
    mode: str = "idempotent",
    path: Path | str | None = None,
) -> dict:
    """Validate + append a single position snapshot row."""
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V7.1 populate helper is RESEARCH only."
    _require_non_empty(as_of, "as_of")
    _require_non_empty(account, "account")
    _require_non_empty(ticker, "ticker")
    if asset_type not in ALLOWED_ASSET_TYPE:
        raise PopulatePortfolioValidationError(
            f"asset_type must be in {sorted(ALLOWED_ASSET_TYPE)}, "
            f"got {asset_type!r}"
        )

    p = Path(path) if path else DEFAULT_POSITIONS_FILE
    row = PositionRow(
        as_of=as_of, account=account, ticker=ticker,
        company_name=company_name, asset_type=asset_type,
        quantity=quantity, average_cost=average_cost,
        last_price=last_price, market_value=market_value,
        unrealized_pnl=unrealized_pnl, realized_pnl=realized_pnl,
        currency=currency, sector=sector, theme=theme,
        source=source, notes=notes,
    )
    ensure_positions_header(p)
    result = append_position_rows([row], p, mode=mode)
    return {"path": str(p), "row_kind": "position", **result}


def add_transaction_row(
    *,
    date: str,
    account: str,
    ticker: str,
    side: str,
    quantity: str = "",
    price: str = "",
    fees: str = "",
    currency: str = "USD",
    reason: str = "",
    linked_thesis: str = "",
    source: str = "",
    notes: str = "",
    mode: str = "idempotent",
    path: Path | str | None = None,
) -> dict:
    """Validate + append a single transaction row."""
    assert quantbot.LIVE_TRADING_ENABLED is False, \
        "V7.1 populate helper is RESEARCH only."
    _require_non_empty(date, "date")
    _require_non_empty(account, "account")
    _require_non_empty(ticker, "ticker")
    _require_non_empty(side, "side")
    if side not in ALLOWED_TRANSACTION_SIDE:
        raise PopulatePortfolioValidationError(
            f"side must be in {sorted(ALLOWED_TRANSACTION_SIDE)}, "
            f"got {side!r}"
        )

    p = Path(path) if path else DEFAULT_TRANSACTIONS_FILE
    row = TransactionRow(
        date=date, account=account, ticker=ticker, side=side,
        quantity=quantity, price=price, fees=fees, currency=currency,
        reason=reason, linked_thesis=linked_thesis,
        source=source, notes=notes,
    )
    ensure_transactions_header(p)
    result = append_transaction_rows([row], p, mode=mode)
    return {"path": str(p), "row_kind": "transaction", **result}


# --------------------------------------------------------------------------- #
# argparse CLI
# --------------------------------------------------------------------------- #
def _add_common_mode(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--mode",
        choices=("idempotent", "append", "strict"),
        default="idempotent",
        help="Write mode (default: idempotent).",
    )


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=("V7.1 — Portfolio data-population helper. Manual "
                     "entries only. No network. No trading. No broker."),
    )
    sub = ap.add_subparsers(dest="subcommand", required=True)

    # --- add-position --------------------------------------------------- #
    p_pos = sub.add_parser(
        "add-position",
        help="Append one row to data/portfolio/positions.csv",
    )
    p_pos.add_argument("--as-of", required=True,
                        help="Snapshot date (ISO YYYY-MM-DD).")
    p_pos.add_argument("--account", required=True)
    p_pos.add_argument("--ticker", required=True)
    p_pos.add_argument("--company-name", default="")
    p_pos.add_argument("--asset-type", default="N_A",
                        choices=sorted(ALLOWED_ASSET_TYPE))
    p_pos.add_argument("--quantity", default="")
    p_pos.add_argument("--average-cost", default="")
    p_pos.add_argument("--last-price", default="")
    p_pos.add_argument("--market-value", default="")
    p_pos.add_argument("--unrealized-pnl", default="")
    p_pos.add_argument("--realized-pnl", default="")
    p_pos.add_argument("--currency", default="USD")
    p_pos.add_argument("--sector", default="")
    p_pos.add_argument("--theme", default="")
    p_pos.add_argument("--source", default="")
    p_pos.add_argument("--notes", default="")
    p_pos.add_argument("--path", default=None,
                        help="Override positions.csv path.")
    _add_common_mode(p_pos)

    # --- add-transaction ----------------------------------------------- #
    p_tx = sub.add_parser(
        "add-transaction",
        help="Append one row to data/portfolio/transactions.csv",
    )
    p_tx.add_argument("--date", required=True,
                       help="Trade date (ISO YYYY-MM-DD).")
    p_tx.add_argument("--account", required=True)
    p_tx.add_argument("--ticker", required=True)
    p_tx.add_argument("--side", required=True,
                       choices=sorted(ALLOWED_TRANSACTION_SIDE))
    p_tx.add_argument("--quantity", default="")
    p_tx.add_argument("--price", default="")
    p_tx.add_argument("--fees", default="")
    p_tx.add_argument("--currency", default="USD")
    p_tx.add_argument("--reason", default="")
    p_tx.add_argument("--linked-thesis", default="")
    p_tx.add_argument("--source", default="")
    p_tx.add_argument("--notes", default="")
    p_tx.add_argument("--path", default=None,
                       help="Override transactions.csv path.")
    _add_common_mode(p_tx)

    return ap


def cli(argv: list[str] | None = None) -> int:
    ap = _build_parser()
    args = ap.parse_args(argv)

    try:
        if args.subcommand == "add-position":
            summary = add_position_row(
                as_of=args.as_of,
                account=args.account,
                ticker=args.ticker,
                company_name=args.company_name,
                asset_type=args.asset_type,
                quantity=args.quantity,
                average_cost=args.average_cost,
                last_price=args.last_price,
                market_value=args.market_value,
                unrealized_pnl=args.unrealized_pnl,
                realized_pnl=args.realized_pnl,
                currency=args.currency,
                sector=args.sector,
                theme=args.theme,
                source=args.source,
                notes=args.notes,
                mode=args.mode,
                path=args.path,
            )
        elif args.subcommand == "add-transaction":
            summary = add_transaction_row(
                date=args.date,
                account=args.account,
                ticker=args.ticker,
                side=args.side,
                quantity=args.quantity,
                price=args.price,
                fees=args.fees,
                currency=args.currency,
                reason=args.reason,
                linked_thesis=args.linked_thesis,
                source=args.source,
                notes=args.notes,
                mode=args.mode,
                path=args.path,
            )
        else:
            ap.error(f"unknown subcommand {args.subcommand!r}")
            return 2
    except (PopulatePortfolioValidationError,
            PortfolioSchemaError) as exc:
        print(f"populate-portfolio rejected: {exc}", file=sys.stderr)
        return 2

    print(
        f"Appended {summary['n_appended']} {summary['row_kind']} row(s) "
        f"(skipped {summary['n_skipped']}) "
        f"to {Path(summary['path']).name} [mode={args.mode}]."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
