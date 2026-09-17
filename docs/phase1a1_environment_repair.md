# Phase 1A.1 — Environment repair and full-test verification

Date: 2026-09-17  
Scope: Python environment diagnosis, exact-version `statsmodels` repair, and
test verification. No production or test source was changed during Phase 1A.1.

## Active environment

- Interpreter: `C:\Users\kerem\OneDrive\Desktop\quant_trading_bot\.venv\Scripts\python.exe`
- Python: 3.12.10, 64-bit CPython
- Virtual-environment prefix: `C:\Users\kerem\OneDrive\Desktop\quant_trading_bot\.venv`
- Base interpreter: `C:\Users\kerem\AppData\Local\Programs\Python\Python312`
- `include-system-site-packages = false`
- pip: 26.1.2 from the project virtual environment
- pytest: 9.0.3

Python 3.12 satisfies the project's `>=3.11` requirement. Both
`pyproject.toml` and `requirements.txt` specify `statsmodels>=0.14`; the installed
0.14.6 version is compatible with those declarations and declares Python >=3.9.
There was no pip configuration overriding indexes, package locations, or
installation behavior. The package was a CPython 3.12 Windows AMD64 binary wheel.

## Diagnosis

Before repair, `statsmodels-0.14.6.dist-info/RECORD` listed 1,396 non-bytecode
package files. Only 272 existed; 1,124 were absent. Missing paths included
`statsmodels/compat/patsy.py`, even though `statsmodels/__init__.py` imports it,
as well as entire major package directories such as `base`, `compat`, `datasets`,
`regression`, `robust`, and `stats`.

This proves the installed payload was incomplete while its 0.14.6 metadata
remained. The source import is valid and the selected version is compatible;
this was not a source-code API mistake or a need to change versions.

The `.venv`, `site-packages`, and `statsmodels` directories are Microsoft
OneDrive directory reparse points (`0x9000e01a`) because the virtual environment
lives under the OneDrive-backed repository. Other distribution metadata is also
missing: pip does not see pandas, certifi, rich, or pyarrow as installed even
though their package directories exist and pandas imports as 3.0.3. This is
consistent with broader partial synchronization or file loss in the virtual
environment. The repository and environment contain no pip/OneDrive event log
that can identify whether an interrupted package operation, OneDrive sync,
restore, selective availability, or another external deletion caused the loss.
The exact historical event therefore cannot be determined from current evidence.

## Package action performed

One package action was performed:

```powershell
& .\.venv\Scripts\python.exe -B -m pip install --force-reinstall --no-deps statsmodels==0.14.6
```

pip used its cached `statsmodels-0.14.6-cp312-cp312-win_amd64.whl` (9.5 MB),
uninstalled the incomplete 0.14.6 distribution, and installed 0.14.6 again.
`--no-deps` prevented dependency changes. No package was upgraded or downgraded,
pip itself was not upgraded, and no production workaround or import shim was
added.

After repair:

- all 1,396 manifest-listed non-bytecode `statsmodels` files exist;
- zero manifest-listed package files are missing;
- `statsmodels.__version__` is 0.14.6;
- `statsmodels.api` imports successfully;
- `statsmodels.compat.patsy` imports successfully.

## Test verification

Commands used `-B`, disabled the pytest cache plugin, and cleared the project's
quiet default so complete summaries were visible.

### Previously blocked modules

```powershell
& .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider \
  -o addopts='' -ra --tb=short \
  tests/test_v2_improvements.py tests/test_v21_cleanup.py tests/test_s03_pairs.py
```

Result: **32 passed in 37.18 seconds**.

- Failures: 0
- Errors: 0
- Collection errors: 0
- Skips: 0
- Warnings: 0

### Phase 1A accounting regressions and invariants

```powershell
& .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider \
  -o addopts='' -ra --tb=short tests/test_etf_accounting_regressions.py
```

Result: **38 passed in 1.47 seconds**.

- Failures: 0
- Errors: 0
- Collection errors: 0
- Skips: 0
- Warnings: 0

### Full project suite

```powershell
& .\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider \
  -o addopts='' -ra --tb=short
```

Result: **1,833 passed in 190.16 seconds (3 minutes 10 seconds)**.

- Failures: 0
- Errors: 0
- Collection errors: 0
- Skips: 0
- Warnings: 0

No test exposed a Phase 1A accounting regression. Phase 1A is fully verified by
the currently collected project test suite.

## Residual environment health finding

`pip check` still exits nonzero because distribution metadata for several other
packages is absent:

- `statsmodels`, `streamlit`, and `yfinance` report pandas missing;
- `curl-cffi` and `requests` report certifi missing;
- `curl-cffi` reports rich missing;
- `streamlit` reports pyarrow missing.

Pandas, certifi, rich, and pyarrow package directories exist as OneDrive reparse
points, and pandas imports successfully as 3.0.3. These residual metadata issues
did not cause any of the 1,833 tests to fail and were not repaired because Phase
1A.1 authorized the required `statsmodels` repair, not a broad environment
rebuild. A future environment-hardening step should recreate `.venv` outside a
OneDrive-synchronized directory from a locked dependency set instead of relying
on the current partially synchronized environment.
