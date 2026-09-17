# Phase 1C — Current environment and reproducibility requirements

Observed on 2026-09-17. Read-only environment inspection; no install, upgrade,
downgrade, relocation, rebuild or environment-variable mutation in Phase 1C.

## Exact current runtime

| Item | Observed value |
|---|---|
| Project Python | `C:\Users\kerem\OneDrive\Desktop\quant_trading_bot\.venv\Scripts\python.exe` |
| Python | CPython 3.12.10, 64-bit Windows AMD64, MSC v.1943 |
| sys.prefix | `C:\Users\kerem\OneDrive\Desktop\quant_trading_bot\.venv` |
| sys.base_prefix | `C:\Users\kerem\AppData\Local\Programs\Python\Python312` |
| Base executable (pyvenv.cfg) | `C:\Users\kerem\AppData\Local\Programs\Python\Python312\python.exe` |
| System site packages | false |
| pip | 26.1.2 |
| pytest | 9.0.3 |
| pytest plugin observed | anyio 4.13.0 |
| Test import path | `src`, configured by pyproject.toml |

Every observed distribution below resides under this environment's
`.venv\Lib\site-packages`; pandas imports from that same location.

| Dependency | Repository declaration | Observed runtime/distribution |
|---|---|---|
| numpy | >=1.26 | 2.4.6 |
| pandas | >=2.1 | Imports as 3.0.3; distribution metadata missing |
| scipy | >=1.11 | 1.17.1 |
| statsmodels | >=0.14 | 0.14.6 |
| matplotlib | >=3.8 | 3.10.9 |
| yfinance | >=0.2.40 | 1.4.1 |
| pytest | >=7.4 | 9.0.3 |
| patsy | transitive dependency | 1.0.2 |

`pyproject.toml` requires Python >=3.11 and the same six core lower bounds as
`requirements.txt`. Pytest is an optional test extra in pyproject and included directly
in requirements. These are compatible *ranges*, not a reproducible lock. They do not
pin Python, direct/transitive package versions, wheel hashes or complete optional
application/research dependencies. The installed environment contains additional
packages beyond this core declaration, including application dependencies.

## Incomplete-installation evidence remains relevant

Phase 1A.1 repaired the intended exact statsmodels version, 0.14.6. This phase
rechecked its RECORD manifest: **1,396 non-bytecode package files, zero missing**.
The exact historical cause of the earlier 1,124 missing files still cannot be
determined. Its OneDrive/reparse-point location and other incomplete metadata are
consistent with external synchronization/file loss or an interrupted operation,
but do not prove which event occurred. No speculative cause is presented as fact.

Current metadata is still missing for **pandas, certifi, rich and pyarrow**.
Pandas nevertheless imports as 3.0.3. `pip check` exits nonzero with these seven
dependency reports:

```text
curl-cffi 0.15.0 requires certifi, which is not installed.
curl-cffi 0.15.0 requires rich, which is not installed.
requests 2.34.2 requires certifi, which is not installed.
statsmodels 0.14.6 requires pandas, which is not installed.
streamlit 1.58.0 requires pandas, which is not installed.
streamlit 1.58.0 requires pyarrow, which is not installed.
yfinance 1.4.1 requires pandas, which is not installed.
```

These are metadata-based reports. They are not proof that every named package's
importable payload is absent. Conversely, a successful import is not proof of a
complete installation. This environment's passing tests do not certify a clean
dependency inventory. A `pip freeze` from it would be incomplete and must not be
misrepresented as a reliable lock file.

## Required Phase 2 work — not performed here

1. Select the supported Python/platform and core/test/optional application profiles.
   Inventory actual imports in addition to the two existing dependency declarations.
2. Resolve a complete, reviewed direct/transitive dependency set from verified
   distributions. Start from the observed versions where appropriate; do not infer
   that a version upgrade is required just because metadata is missing.
3. Produce platform-appropriate pinned lock artifacts including hashes and document
   dependency provenance. Include optional profiles explicitly; avoid incidental
   packages from this damaged environment.
4. Create a fresh virtual environment outside OneDrive/cloud synchronization—for
   example a dedicated local environment directory—without moving or copying the
   existing site-packages payload as the recreation method.
5. Install only from the reviewed lock, verify wheel/package integrity and interpreter
   selection, and require a clean `pip check`.
6. Run the complete project suite and unchanged Phase 1A/1B/1C invariants from a clean
   checkout containing all required source, including `src/quantbot/data`.
7. Record the interpreter, lock hash, platform and test outcome. Keep credentials,
   local datasets, cache outputs and virtual environments outside tracked source.

No Phase 2 environment, lock file, package installation, Docker configuration or
monitoring was created by this documentation step.
