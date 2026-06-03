# CLAUDE.md - Project Memory for Claude Code

## Project Goal
Build a Python quantitative trading research and backtesting bot based on strategy ideas extracted from:
- Inside the Black Box by Rishi K. Narang
- Options, Futures, and Other Derivatives by John C. Hull
- Option Volatility & Pricing by Sheldon Natenberg

This is a research/backtesting project. Do not implement live trading in v1.

## Non-Negotiable Rules
- Do not promise profitability.
- Do not write live broker execution code.
- Do not use naked short options.
- Do not ignore transaction costs.
- Do not use future data in signals, pair selection, factor rankings, volatility forecasts, or exits.
- Do not use options last price as executable price.
- Always model risk, cost, and execution assumptions.
- Prefer simple, testable code over clever code.

## Strategy Priority
Implement first:
1. S01 Multi-Asset Volatility-Targeted Trend Following
2. S03 Pairs / Statistical Arbitrage Mean Reversion
3. S02 Cross-Sectional Factor Blend, price-only v1
4. S04 Carry / Futures Term Structure only if futures data exists

Implement later:
5. S05 Implied-vs-Realized Volatility
6. S06 Long Gamma Scalping
7. S07 Volatility Skew / Risk Reversal
8. S08 Calendar / Term Structure Vol Spread

Tools/overlays:
9. S09 Synthetic Arbitrage Scanner
10. S10 Tail Hedge / Portfolio Insurance Overlay

## Code Style
- Use Python 3.11+.
- Use pandas/numpy for research calculations.
- Keep modules small and testable.
- Use dataclasses where useful.
- Add docstrings for all public functions.
- Add unit tests before or alongside implementation.
- Avoid hidden global state.

## Backtesting Rules
- Signals use data available up to date t.
- Orders execute on next bar, never same bar unless explicitly modeled.
- Costs are applied to every trade.
- All results must report turnover and total costs.
- Position sizing must pass through RiskManager.
- Backtest output must include drawdown and exposure metrics.

## Risk Rules
- Enforce max position size.
- Enforce max gross/net exposure.
- Add drawdown kill switch.
- Add volatility targeting.
- For options, track max loss and Greeks.
- If a risk cannot be modeled, document it and disable live trading assumptions.

## Testing Priorities
1. Data validators catch bad data.
2. Backtest engine has no look-ahead bias.
3. Costs reduce returns.
4. Trend strategy respects position caps.
5. Pairs strategy triggers entry/exit/stop correctly.
6. Options payoff functions match expected shapes.
7. Put-call parity scanner does not flag false opportunities without cost buffer.

## Expected Deliverable
A working research repo that can run at least S01 and S03 backtests with risk/cost reporting, plus options utilities for later strategy expansion.
