"""Render a ``SectorReport`` to Markdown (V6.1, pure).

Read-only formatting. The rendered file is decision-support context — NOT a
broker order, NOT a trading signal. ``LIVE_TRADING_ENABLED`` stays ``False``.
"""

from __future__ import annotations

from pathlib import Path

from .sector_builder import SectorReport


def render_markdown(report: SectorReport) -> str:
    s = report.score
    md: list[str] = [f"# {report.sector} Sector Thesis Tracker — Signal\n"]
    md.append(
        "*Read-only DECISION-SUPPORT output. NOT a trading signal, NOT a "
        "broker order, NOT investment advice. "
        "`LIVE_TRADING_ENABLED = False`.*\n"
    )
    md.append(f"\n- Sector: **{report.sector}**")
    md.append(f"- **Signal: {s.signal}**")
    md.append(
        f"- Normalized score: **{s.normalized_score:+.3f}** "
        f"(raw {s.raw_score:+.1f} / total weight {s.total_weight})"
    )
    md.append(
        f"- Catalysts: {s.n_total} "
        f"(BULL {s.n_bull}, NEUTRAL {s.n_neutral}, "
        f"NEAR_THRESHOLD {s.n_near_threshold}, BROKEN {s.n_broken})"
    )
    trig = ", ".join(s.triggered_exits) if s.triggered_exits else "none"
    md.append(
        f"- Emergency exit triggered: **{s.emergency_triggered}** "
        f"(triggered: {trig})"
    )

    if s.top_bull_drivers:
        md.append("\n## Top bull drivers")
        for name in s.top_bull_drivers:
            md.append(f"- {name}")

    if s.top_risks:
        md.append("\n## Top risks (BROKEN / NEAR_THRESHOLD)")
        for name in s.top_risks:
            md.append(f"- {name}")

    md.append("\n## Catalysts (raw)")
    md.append(
        "| catalyst_id | tier | status | catalyst_name | threshold | "
        "current | action_if_broken |"
    )
    md.append("|---|---|---|---|---|---|---|")
    for c in report.catalysts:
        md.append(
            f"| {c.catalyst_id} | {c.tier} | {c.status} | {c.catalyst_name} | "
            f"{c.threshold} | {c.current_value} | {c.action_if_broken} |"
        )

    if report.exits:
        md.append("\n## Emergency exits")
        md.append("| exit_id | status | scenario | trigger | action |")
        md.append("|---|---|---|---|---|")
        for e in report.exits:
            md.append(
                f"| {e.exit_id} | {e.current_status} | {e.scenario} | "
                f"{e.trigger_condition} | {e.action} |"
            )

    md.append("\n## Scoring scheme (pre-declared, not optimized)")
    md.append("- Tier 1 weight = 2; Tier 2 weight = 1.")
    md.append("- Status values: BULL=+1, NEUTRAL=0, NEAR_THRESHOLD=-1, BROKEN=-2.")
    md.append("- Normalized score = sum(weight × status) / sum(weight).")
    md.append(
        "- Bands: >= 0.50 ACCUMULATE; >= 0.20 SELECTIVE_BUY; "
        ">= -0.10 HOLD; >= -0.30 AVOID_NEW_BUY; "
        ">= -0.60 REDUCE; else EXIT_WATCH."
    )
    md.append("- Any TRIGGERED emergency exit overrides → EXIT_WATCH.")
    md.append(
        "- **No broker orders are produced.** The signal label is a research "
        "recommendation only; validation in V6.6 is separate."
    )

    return "\n".join(md) + "\n"


def write_markdown(report: SectorReport, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render_markdown(report), encoding="utf-8")
    return p


__all__ = ["render_markdown", "write_markdown"]
