"""No-arbitrage scanners (RESEARCH / REPORT ONLY - never auto-trades in v1).

Apparent violations are usually stale quotes, early-exercise/dividend effects,
or hard-to-borrow - not free money. A candidate is only flagged if the edge
beats worst-case execution (cross every bid/ask) PLUS a safety buffer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..costs.transaction_costs import OptionsCostModel


def put_call_parity_value(
    call: float, put: float, strike: float, rate: float, dte: float,
    spot: float, dividend_yield: float = 0.0,
) -> float:
    """Parity residual for European options:

        residual = (C - P) - (S·e^{-qT} - K·e^{-rT})

    ~0 means parity holds. Large |residual| suggests a mispricing OR (more
    often) bad data / American or dividend effects.
    """
    T = dte / 365.0
    synthetic = spot * np.exp(-dividend_yield * T) - strike * np.exp(-rate * T)
    return float((call - put) - synthetic)


def scan_parity_violations(
    chain: pd.DataFrame,
    underlying_price: float,
    rate: float = 0.03,
    dividend_yield: float = 0.0,
    cost_model: OptionsCostModel | None = None,
    safety_buffer: float = 0.05,
    european_only: bool = True,
) -> pd.DataFrame:
    """Flag conversion/reversal opportunities net of worst-case costs.

    Uses executable prices (cross the spread): buy at ask, sell at bid. Returns
    a DataFrame of *flags only* - no orders are ever generated.
    """
    cm = cost_model or OptionsCostModel()
    rows = []
    for (exp, K), grp in chain.groupby(["expiration", "strike"]):
        calls = grp[grp["option_type"] == "call"]
        puts = grp[grp["option_type"] == "put"]
        if calls.empty or puts.empty:
            continue
        c, p = calls.iloc[0], puts.iloc[0]
        dte = float(c["dte"])
        T = dte / 365.0
        pv_k = float(K) * np.exp(-rate * T)
        spot_adj = underlying_price * np.exp(-dividend_yield * T)

        # Conversion: buy call (ask), sell put (bid), short stock. Reversal is
        # the mirror. Evaluate both with worst-case fills.
        legs = [
            {"contracts": 1, "bid": c["bid"], "ask": c["ask"]},
            {"contracts": 1, "bid": p["bid"], "ask": p["ask"]},
        ]
        cost = cm.structure_cost(legs) / 100.0  # per-share terms

        conv_edge = (p["bid"] - c["ask"]) + spot_adj - pv_k
        rev_edge = (c["bid"] - p["ask"]) - spot_adj + pv_k
        best = max(conv_edge, rev_edge)
        if best - cost - safety_buffer > 0:
            rows.append(
                {
                    "expiration": exp,
                    "strike": float(K),
                    "dte": dte,
                    "edge_per_share": round(best, 4),
                    "est_cost_per_share": round(cost, 4),
                    "safety_buffer": safety_buffer,
                    "flag": "PARITY_DEVIATION",
                    "note": "stale-data/dividend/borrow more likely than arb"
                    + ("" if european_only else "; check early exercise"),
                }
            )
    return pd.DataFrame(rows)


def scan_box_spreads(
    chain: pd.DataFrame, rate: float = 0.03, cost_model: OptionsCostModel | None = None,
    safety_buffer: float = 0.05,
) -> pd.DataFrame:
    """A box (bull call + bear put, strikes K1<K2) should be worth
    (K2-K1)·e^{-rT}. Flag deviations beyond costs + buffer."""
    cm = cost_model or OptionsCostModel()
    rows = []
    for exp, grp in chain.groupby("expiration"):
        strikes = sorted(grp["strike"].unique())
        for i in range(len(strikes)):
            for j in range(i + 1, len(strikes)):
                K1, K2 = strikes[i], strikes[j]
                T = float(grp["dte"].iloc[0]) / 365.0
                fair = (K2 - K1) * np.exp(-rate * T)

                def leg(opt, k):
                    r = grp[(grp["option_type"] == opt) & (grp["strike"] == k)]
                    return None if r.empty else r.iloc[0]

                c1, c2 = leg("call", K1), leg("call", K2)
                p1, p2 = leg("put", K1), leg("put", K2)
                if any(x is None for x in (c1, c2, p1, p2)):
                    continue
                # Worst-case box cost: buy call K1 (ask), sell call K2 (bid),
                # buy put K2 (ask), sell put K1 (bid).
                box_cost = (c1["ask"] - c2["bid"]) + (p2["ask"] - p1["bid"])
                legs = [{"contracts": 1, "bid": x["bid"], "ask": x["ask"]}
                        for x in (c1, c2, p1, p2)]
                tc = cm.structure_cost(legs) / 100.0
                edge = abs(fair - box_cost) - tc - safety_buffer
                if edge > 0:
                    rows.append(
                        {
                            "expiration": exp, "K1": K1, "K2": K2,
                            "fair_value": round(fair, 4),
                            "box_cost": round(box_cost, 4),
                            "edge_per_share": round(edge, 4),
                            "flag": "BOX_DEVIATION",
                        }
                    )
    return pd.DataFrame(rows)


def scan_butterfly_convexity(chain: pd.DataFrame) -> pd.DataFrame:
    """Option prices must be convex in strike for a fixed expiry/type:
    mid(K2) <= 0.5·(mid(K1)+mid(K3)) for equally spaced K1<K2<K3.
    Violations almost always indicate stale/bad data - flagged as such."""
    rows = []
    for (exp, opt), grp in chain.groupby(["expiration", "option_type"]):
        g = grp.sort_values("strike")
        ks = g["strike"].to_numpy()
        mids = ((g["bid"] + g["ask"]) / 2.0).to_numpy()
        for i in range(len(ks) - 2):
            if not np.isclose(ks[i + 1] - ks[i], ks[i + 2] - ks[i + 1]):
                continue
            convex_rhs = 0.5 * (mids[i] + mids[i + 2])
            if mids[i + 1] > convex_rhs + 1e-9:
                rows.append(
                    {
                        "expiration": exp, "option_type": opt,
                        "K1": ks[i], "K2": ks[i + 1], "K3": ks[i + 2],
                        "mid_K2": round(mids[i + 1], 4),
                        "convex_bound": round(convex_rhs, 4),
                        "flag": "CONVEXITY_VIOLATION (likely bad data)",
                    }
                )
    return pd.DataFrame(rows)
