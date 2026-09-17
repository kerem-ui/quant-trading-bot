# Phase 2A reproducible Python environment

## Dependency authority

`pyproject.toml` is the sole hand-maintained dependency declaration. Direct
application and test versions match the verified Phase 1 environment. `uv.lock`
pins the complete transitive graph. Resolution excludes artifacts newer than
2026-06-04, the date of the verified Phase 1 environment, so recreating the
lock cannot silently pull later transitive releases. `requirements.txt` is a
compatibility pointer to the project and intentionally contains no second
package list.

The groups are:

- core runtime: NumPy, pandas, SciPy, statsmodels, Matplotlib and yfinance;
- development/test: pytest in the `dev` dependency group;
- optional dashboard: Streamlit in the `dashboard` extra;
- optional broker: an explicitly empty `broker` extra because this research
  checkpoint imports no IBKR SDK and does not implement broker execution.

The supported interpreter line is CPython 3.12. `.python-version` selects the
verified patch release, 3.12.10. The environment lives outside OneDrive to
avoid repeating the incomplete-package failure observed in Phase 1A.1.

## Clean Windows installation

Prerequisites are Git, Python, access to the private repository and network
access to the configured Python package index. In PowerShell:

```powershell
python -m pip install uv==0.11.8
git clone --branch phase2-reproducibility --single-branch https://github.com/kerem-ui/quant-trading-bot.git C:\QuantProjects\quant_trading_bot_phase2
Set-Location C:\QuantProjects\quant_trading_bot_phase2

$env:UV_PROJECT_ENVIRONMENT = 'C:\QuantEnvs\quant_trading_bot_phase2'
uv sync --locked --all-extras --group dev --python 3.12.10

uv lock --check
uv pip check --python "$env:UV_PROJECT_ENVIRONMENT\Scripts\python.exe"
& "$env:UV_PROJECT_ENVIRONMENT\Scripts\python.exe" -m pytest
```

`uv sync --locked` must fail rather than rewrite the lock if the declaration
and lock differ. `--all-extras --group dev` installs the core, dashboard and
test sets; the broker extra currently adds nothing by design.

For an offline installation, the lock alone is insufficient: Python wheels for
the target Windows/Python platform must already exist in a local package cache
or an internal mirror. No wheelhouse is committed to this repository.

## Phase 2A verification record

Verified on Windows AMD64 with CPython 3.12.10 and uv 0.11.8:

- primary environment: `C:\QuantEnvs\quant_trading_bot_phase2`;
- resolved and installed distributions: 71;
- `uv lock --check`: passed;
- `uv pip check`: all 71 installed distributions compatible;
- critical imports: NumPy, pandas, SciPy, statsmodels, Matplotlib, yfinance,
  pytest, Streamlit, PyArrow, certifi, Rich and quantbot all passed;
- Phase 1A/1B/1C regressions: 178 passed in 7.16 seconds;
- complete clean-clone suite, started with no `/data` directory: 1,385 passed,
  14 skipped, 0 failed in 147.00 seconds. The 14 skips are optional SEC-cache integration checks and
  identify their missing local cache prerequisites explicitly.

A second environment at `C:\QuantEnvs\quant_trading_bot_phase2_verify` was
created from the same locked files. It installed the same 71 distributions,
passed `uv pip check`, passed all critical imports, and passed the 178 Phase 1
regressions in 6.96 seconds.

The clean clone exposed two pre-existing checkpoint reproducibility gaps rather
than dependency failures. The committed Phase 1 regression expected the
cash-and-quantity version of the S01 diagnostic, but its implementation file
had been omitted from the checkpoint; the verified ledger-based diagnostic was
restored without changing engine economics. Several legacy smoke tests also
assumed ignored local data was committed. They now use small repository-owned
research fixtures, a generated deterministic SPY series, and a temporary
SEC-format fixture. Their assertions remain unchanged and no production data
path or storage behavior changed.
