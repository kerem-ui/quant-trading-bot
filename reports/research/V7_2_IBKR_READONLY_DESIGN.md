# V7.2 — IBKR Read-Only Sync (DESIGN ONLY)

_Hand-written design document. **No IBKR code has been added.** No `ib_insync` is imported anywhere in the repository. The platform remains local-only, read-only, and trading-free. Implementation is gated on this design being signed off and on the V7.0.1 launch/mobile workflow landing first._

**Status: PLANNING ONLY.** This document specifies what V7.2 _would_ do if implemented. It does not implement anything. `LIVE_TRADING_ENABLED` remains `False`.

---

## 1. Purpose

V7.1 ships a manually-curated portfolio CSV at `data/portfolio/positions.csv`. The Portfolio, Protection, and PortTech pages all read this file. Manual entry works for testing the platform but is brittle for sustained operator use.

V7.2 is the **one-way read-only bridge** from Interactive Brokers (TWS or IB Gateway) into that same CSV. Concretely:

- A future `scripts/sync_portfolio_ibkr.py` would read the current portfolio from a running IBKR session and append rows in the V7.1 schema to `data/portfolio/positions.csv`.
- The platform never imports any IBKR module. Every page continues to read CSV only.
- The sync is opt-in (Section 4). Without explicit operator action, the script is a no-op.

### Non-goals

- **No order placement, no order preview, no buy/sell button, no trade execution, no hedge execution.** This bears repeating because IBKR's API is best known for order routing. V7.2 explicitly forbids that surface.
- No live price fetch for trading decisions. The platform's existing stale-as-entered policy stands.
- No account modification, no fund transfer, no settings change.
- No backtesting integration. V6.9 backtest substrate is unrelated; V7.2 contributes only operator-curated snapshots, not historical price/volume data.

### Why a separate document instead of starting code

The V7.0 → V7.8 → V7.1 → V7.7 → V7.4 ladder has demonstrated a consistent shape: schema → readers → page → optional populate helper. Every new page so far has been **purely local**. V7.2 is the first milestone that introduces a networked dependency (IBKR's socket protocol). That dependency carries unique risk:

1. The same module that can read positions can also place orders. Discipline must be code-level, not project-level.
2. `ib_insync` (the standard Python wrapper) is not currently installed; adding it as a dependency is a project-level decision.
3. Authentication is per-session and requires a running TWS/Gateway process — the failure mode "TWS isn't running" must be the default no-op, not a crash.

Specifying these constraints in writing first — and codifying them as grep tests in this V7.2 milestone — means the future V7.2 implementation has a hard, testable target.

---

## 2. Strict guardrails

The following are **hard project-level invariants**. The V7.2 implementation milestone, when it eventually happens, must preserve all of them. Grep tests in `tests/test_v7_2_ibkr_design.py` already enforce the most important ones today.

| Guardrail | Enforcement |
|---|---|
| `LIVE_TRADING_ENABLED` remains `False` | `quantbot.LIVE_TRADING_ENABLED is False` assertion |
| No orders | grep tests for `placeOrder`, `place_order`, `submit_order`, `bracketOrder` across `src/`, `scripts/`, `apps/` |
| No order preview | grep tests for `whatIfOrder`, `previewOrder` |
| No buy/sell button | grep tests in `apps/` for `buy_button`, `sell_button` |
| No trade execution | grep tests for `execute_trade`, `place_trade`, `submit_trade`, `execute_order` |
| No hedge execution | grep tests for `execute_hedge`, `submit_hedge`, `place_hedge`, `hedge_order` |
| No live trading | `LIVE_TRADING_ENABLED` assert + no broker-import surface |
| Opt-in only | `--enable-ibkr` flag AND `IBKR_READONLY_ENABLED=1` env var required (Section 4) |
| Default behaviour is no-op | Without both, the script prints a one-line message and exits 0 |
| Platform must not import IBKR | grep `apps/portfolio_platform.py` for `ib_insync` / `ibapi` — must be absent |

### Enforcement model

The guardrails are enforced by a combination of:

- **Test-side grep** of the new V7.2 source surfaces for forbidden tokens. Mirrors the pattern used in V7.1, V7.7, V7.4 surfaces.
- **Module isolation.** The IBKR call lives in `src/quantbot/research/portfolio/ibkr_sync.py` (when eventually implemented). Nothing in `apps/` imports it. The script in `scripts/sync_portfolio_ibkr.py` is the only consumer.
- **No conditional execution.** If either flag is missing, `cli()` prints a friendly message and exits 0. No partial path, no "default to dry-run with a warning". Either both flags are present and the sync runs, or it does nothing.
- **No `__init__.py` re-export.** `src/quantbot/research/portfolio/__init__.py` continues to NOT export anything from `ibkr_sync`. A future operator must import the module by explicit path (`from quantbot.research.portfolio.ibkr_sync import ...`) to even access it. The Portfolio / Protection / PortTech pages cannot accidentally pick it up.

---

## 3. Proposed future files (described in this section, NOT created)

The following files **do not exist** in the repository and are not created by this V7.2 design milestone. They are listed here so the future implementation has a fixed target.

### `src/quantbot/research/portfolio/ibkr_sync.py` (FUTURE)

Single isolated module containing every IBKR call. Surface:

```python
def sync_positions(
    *,
    host: str = "127.0.0.1",
    port: int = 7497,                # 7497 = TWS paper, 7496 = TWS live;
                                      # operator chooses
    client_id: int = 137,
    enabled: bool = False,           # mandatory; True only when both flags pass
    positions_path: Path | str = DEFAULT_POSITIONS_FILE,
    account_name_override: str | None = None,
    write_mode: str = "idempotent",  # mirrors V7.1 append modes
    redact_account_id: bool = True,  # default ON for safety (Section 9)
) -> dict:
    """One-way read-only IBKR position sync. NO ORDERS."""
```

The module must:

- Import `ib_insync` lazily inside `sync_positions` (not at module-import time) so a `from quantbot.research.portfolio.ibkr_sync import sync_positions` never triggers the `ib_insync` dependency.
- Refuse to do anything when `enabled is False`. Return `{"status": "disabled"}` and exit.
- Use only the IBKR API methods enumerated in Section 5 (`Allowed`). Any other call is a code review failure.
- Convert each IBKR `Position` object to a V7.1-schema `PositionRow` via a single pure adapter (`_position_to_row`) that can be unit-tested without a live IBKR session.
- Call `append_position_rows(...)` from V7.1's readers module to write. No direct CSV write.
- On any exception, log the error class (not the message — which might include account identifiers) and return `{"status": "error", "n_appended": 0, "error_class": <class name>}`. Do not raise into the script.

### `scripts/sync_portfolio_ibkr.py` (FUTURE)

Thin CLI wrapper. Argparse parses the two required flags and calls `sync_positions(...)`. The script's body is essentially:

```python
def cli(argv):
    args = _build_parser().parse_args(argv)
    if not args.enable_ibkr or os.environ.get("IBKR_READONLY_ENABLED") != "1":
        print(
            "IBKR sync disabled. Run with `--enable-ibkr` AND "
            "`IBKR_READONLY_ENABLED=1` to enable. (Default is no-op.)",
            file=sys.stderr,
        )
        return 0
    from quantbot.research.portfolio.ibkr_sync import sync_positions
    result = sync_positions(enabled=True, ...)
    print(f"IBKR sync result: {result}")
    return 0
```

The deferred `from … import sync_positions` means the script does not load `ib_insync` unless the operator has explicitly opted in.

### `tests/test_ibkr_readonly_sync.py` (FUTURE)

Test plan in Section 8.

---

## 4. Required future flags

The future sync script must require **both**:

1. **CLI flag:** `--enable-ibkr` (argparse, `action="store_true"`, no abbreviations).
2. **Environment variable:** `IBKR_READONLY_ENABLED=1`.

Both must be true simultaneously. Either alone is insufficient.

### Rationale

- **CLI flag alone is too easy to set in muscle memory.** An operator who has run the script before with a different intention might re-run it without thinking.
- **Env var alone is too easy to leak.** An `IBKR_READONLY_ENABLED=1` set in `.bashrc` would mean every accidental script invocation tries to connect.
- **Both together** require deliberate, recent operator intent: the flag must be on this command line, and the env var must be set in this shell.

### Default behaviour

When either flag is missing, the script prints exactly:

```
IBKR sync disabled. Run with `--enable-ibkr` AND `IBKR_READONLY_ENABLED=1` to enable. (Default is no-op.)
```

…and exits 0. No CSV is touched. No network call is attempted. No `ib_insync` is loaded.

### No "preview" or "dry-run" flag

A `--dry-run` would imply the operator can test the integration without committing — but a dry-run still loads `ib_insync` and still connects to TWS. That contradicts the "no live trading attempts" stance. The simpler discipline is: either the sync runs for real (both flags) or it does nothing (default).

---

## 5. Allowed / disallowed IBKR operations

### Allowed (design-only list — future code must call ONLY these)

| API call | Purpose |
|---|---|
| `IB.connect(host, port, clientId, readonly=True)` | Establish the read-only session. The `readonly=True` parameter is supported by `ib_insync` and must be passed unconditionally. |
| `IB.reqPositions()` (or `IB.positions()` after a wait) | Read current positions across all accounts the connection has visibility on. |
| `IB.accountSummary()` or `IB.reqAccountSummary(...)` | Read coarse account totals (NetLiquidation, TotalCashValue, BuyingPower). Used only to populate `market_value` / cash placeholder rows if useful. |
| `IB.disconnect()` | Clean session teardown. Must run in a `finally` block. |

### Explicitly disallowed (future code MUST NOT call these — grep-tested)

- `IB.placeOrder`, `IB.placeOrderAsync`, any `placeOrder*` variant.
- `IB.cancelOrder`, `IB.reqGlobalCancel`.
- `IB.bracketOrder`, `IB.oneCancelsAll`.
- `IB.qualifyContracts` for option contracts (no options surface in V7.2 at all).
- `IB.reqMktData` when used to drive trading decisions. (Acceptable only as a deliberate, isolated, future V7.X read-only price snapshot that lands in the V7.8 sector ETF scoreboard; out of scope for V7.2.)
- `IB.exerciseOptions`.
- Any method named `*Order*`, `*Trade*`, `*Exercise*`, `*Exec*`.
- Any method that creates, modifies, or cancels orders, including the FA (Financial Advisor) profile management calls.

The grep test in this V7.2 milestone enumerates these as forbidden tokens and asserts they appear nowhere in `src/quantbot/research/portfolio/` or `scripts/sync_portfolio_ibkr.py` (the latter doesn't exist yet, so the test only fires when the file is added).

### `readonly=True` enforcement

The `IB.connect(...)` call must include `readonly=True`. The grep test in V7.2 enforces this by asserting that if `IB.connect(` ever appears in the future `ibkr_sync.py`, the same line (or the next two lines) contains `readonly=True`. This guards against an honest typo turning a read-only sync into a writeable session.

---

## 6. Failure-mode design

The platform must remain usable regardless of TWS / IBKR state.

| Failure | Behaviour |
|---|---|
| TWS / Gateway not running | `IB.connect()` raises `ConnectionRefusedError`. The wrapper catches it, logs the error class, returns `{"status": "error", "error_class": "ConnectionRefusedError", "n_appended": 0}`. CSV is not touched. Script prints a friendly message and exits 0. |
| Auth failed (paper account locked, FA mode mismatch) | Same as above — catch, log error class only (no message), return `error`, exit 0. |
| Connection succeeds but `reqPositions()` returns empty | Write nothing. Return `{"status": "empty", "n_appended": 0}`. Do NOT write a `DATA_GAP` row — the operator's previous snapshot is more useful than an empty one. |
| Position present but cannot be mapped (e.g. unknown asset type, missing contract symbol) | Skip the row, log the contract identifier (redacted per Section 9), continue. Return `{"status": "partial", "n_appended": N, "n_skipped_unmappable": M}`. |
| Network timeout mid-sync | `ib_insync`'s `RequestError` / `TimeoutError`. Same catch-log-return-0 pattern. CSV not touched. |
| Operator passes `--enable-ibkr` but `IBKR_READONLY_ENABLED` env var is missing | Print disabled message, exit 0. (Section 4.) |
| Operator passes env var but no `--enable-ibkr` flag | Same. |
| `ib_insync` not installed | The lazy import at the top of `sync_positions` raises `ImportError`. The wrapper catches it explicitly and returns `{"status": "ib_insync_not_installed", "n_appended": 0}`. Script prints a clear message: "ib_insync is not installed. V7.2 requires it; run `pip install ib_insync` (this is the only V7.2 dependency)." This is the only message that mentions installation — and even then, the script does not auto-install. |

### Platform-side invariant

After any failure mode the platform must continue to work as before. Specifically:

- The Portfolio page reads the existing `positions.csv` if present (even if last successful sync was days ago).
- The Protection and PortTech pages render their existing labels against that prior snapshot.
- The Home card's "Portfolio: placeholder / available if CSV exists" continues to reflect file presence, not sync recency.

There is **no** code path where an IBKR failure cascades into a platform render failure. The platform never imports `ibkr_sync.py`.

---

## 7. CSV mapping design

Future `ibkr_sync._position_to_row(...)` must produce a `PositionRow` matching the V7.1 schema exactly. The V7.1 schema is frozen for V7.2 — no new columns. Mapping table:

| V7.1 column | IBKR source | Notes |
|---|---|---|
| `as_of` | `datetime.now(timezone.utc).date().isoformat()` | Snapshot date. |
| `account` | `Position.account` (redacted per Section 9 if `redact_account_id=True`) | Default: redact to last 4 characters. Operator can override per call. |
| `ticker` | `Position.contract.symbol` for stocks/ETFs; for futures, `localSymbol` | Pre-declared mapping table per asset type. |
| `company_name` | `IB.qualifyContracts(...).longName` if available; otherwise blank | Conservative — leave blank rather than guess. |
| `asset_type` | Pre-declared map: `STK→STOCK`, `ETF→ETF`, `OPT→OPTION` (FUTURE V7.X only), `FUT→FUTURE`, `BOND→BOND`, `CASH→CASH`, `*→OTHER` | OPTION mapped but never written in V7.2 since options sync is out of scope. |
| `quantity` | `Position.position` (as string) | Negative quantities are short positions; V7.1 schema is agnostic. |
| `average_cost` | `Position.avgCost` (as string, formatted to 2 decimals) | Per-share or per-contract per IBKR convention. |
| `last_price` | Blank in V7.2 | No `reqMktData` call. Stale-as-entered policy preserved. |
| `market_value` | Blank in V7.2 | Without a live price, no honest market value. Operator-edited values from the prior CSV row are preferred — leave blank in the new row so the Portfolio page's totals fall back to "n/a" rather than fabricating a number. |
| `unrealized_pnl` | Blank in V7.2 | Same reasoning. |
| `realized_pnl` | `IB.accountSummary` `RealizedPnL` if available; otherwise blank | Acceptable because it's a settled number, not a live mark. |
| `currency` | `Position.contract.currency` | Default `"USD"`. |
| `sector` | Blank | V7.2 does not map sectors. V7.1 schema has the column; PortTech / Protection look it up via the V6 ledger, not via positions. |
| `theme` | Blank | Same. |
| `source` | `"IBKR_READONLY"` | Pre-declared constant — operator can see at a glance which rows came from sync vs manual entry. |
| `notes` | `"V7.2 sync; market_value/last_price omitted"` | Pre-declared per-row note explaining the deliberate gaps. |

### Why so many blanks

V7.2's mandate is "read positions, write them to the CSV in the V7.1 schema". It is deliberately silent on live prices because:

1. Pulling `reqMktData` for each position requires careful subscription management; doing it badly can hit IBKR's market data quota.
2. The Portfolio totals card already handles `"n/a"` gracefully (V7.1).
3. Operators who want live values can edit the row manually (they were doing this in V7.1 anyway).
4. A future V7.X may add an optional `--include-last-price` flag that opts into `reqMktData`. That is out of scope here.

### Idempotency

V7.2 sync should default to `mode="idempotent"` (V7.1's existing append mode), keyed on `(as_of, account, ticker)`. Re-running the sync on the same day with the same TWS state is a no-op. This is the same contract every V6.7 / V6.8 / V6.6.2 / V7.1 writer uses.

---

## 8. Testing plan

Future `tests/test_ibkr_readonly_sync.py` must cover the following. Each scenario uses a mock IBKR client (a class with `connect`, `positions`, `accountSummary`, `disconnect` methods) injected at the `ibkr_sync.py` boundary. No live IBKR connection in any test.

| Test | What it asserts |
|---|---|
| `test_disabled_by_default_is_no_op` | Calling `sync_positions(enabled=False)` returns `{"status": "disabled"}`, does not import `ib_insync`, does not touch the CSV. |
| `test_cli_disabled_without_both_flags` | The CLI exits 0 with the disabled message when either `--enable-ibkr` is missing or `IBKR_READONLY_ENABLED` env var is absent. |
| `test_cli_disabled_with_only_flag` | Only `--enable-ibkr`, no env var → disabled. |
| `test_cli_disabled_with_only_env` | Only env var, no flag → disabled. |
| `test_no_import_from_platform` | Grep `apps/portfolio_platform.py` for `ibkr_sync` and `ib_insync` — both must be absent. |
| `test_no_forbidden_order_tokens` | Grep all V7.2 surfaces (`src/quantbot/research/portfolio/ibkr_sync.py`, `scripts/sync_portfolio_ibkr.py`) for the disallowed tokens enumerated in Section 5. |
| `test_readonly_flag_required` | If a future `IB.connect(` appears, the same line (or the next 2 lines) must contain `readonly=True`. |
| `test_position_to_row_mapping` | Mock a `Position` object; assert the resulting `PositionRow` has the expected fields per Section 7's table. `source == "IBKR_READONLY"`, `last_price == ""`, `market_value == ""`. |
| `test_csv_append_idempotent` | Run sync twice with the same mocked positions; second run appends 0 rows. |
| `test_tws_not_running_is_friendly_noop` | Mock `connect` to raise `ConnectionRefusedError`; assert wrapper returns error status, exits 0, does not touch CSV. |
| `test_ib_insync_not_installed_is_friendly_noop` | Mock `import ib_insync` to raise `ImportError`; assert wrapper returns `ib_insync_not_installed` status, exits 0, prints the install hint. |
| `test_partial_mapping_skips_unmappable` | Mock 3 positions, one with an unmappable contract; assert `n_appended == 2, n_skipped_unmappable == 1`. |
| `test_account_id_redacted_by_default` | Mock a `Position` with `account="U12345678"`; assert the written row has redacted account (last 4 chars: `"5678"` or similar). |
| `test_no_credentials_in_logs` | Capture log output during a sync; assert no string matching the mocked account id (in non-redacted form) appears in logs. |
| `test_disconnect_called_even_on_error` | Mock `positions()` to raise; assert `disconnect()` is still called. |
| `test_live_trading_enabled_remains_false` | Standard guardrail. |
| `test_no_thetadata_tokens` | Standard guardrail. |
| `test_no_network_imports_outside_ib_insync` | The V7.2 module may import `ib_insync` (lazy) but must not import `requests`, `urllib`, `aiohttp`, etc. |

### Integration test (gated, default disabled)

A single integration test in `tests/test_ibkr_readonly_sync_integration.py` would run the sync against a paper account. It must:

- Be gated by `IBKR_INTEGRATION_TEST_ENABLED` env var. Default: disabled.
- Mark itself `@pytest.mark.skipif(...)` so CI never runs it.
- Document the operator setup required (TWS paper, port 7497, client id 138, no other clients connected).
- Use a dedicated client id (138, different from the default 137 used by the production sync script) to avoid collisions.
- Assert exactly one of: connection succeeded → at least one position row appended; OR connection failed → no rows appended, friendly error returned. Both outcomes are acceptable; the test only fails if the wrapper raises.

### Tests added in THIS V7.2 design milestone

The companion `tests/test_v7_2_ibkr_design.py` (which IS added by this milestone) is minimal and only verifies:

- The design document exists at `reports/research/V7_2_IBKR_READONLY_DESIGN.md`.
- It contains the required guardrail phrases.
- **No IBKR code has been added.** Grep the entire `src/` + `scripts/` + `apps/` tree for `ib_insync` / `ibapi` / `from ibkr_sync` / `import ibkr_sync` imports — all must be absent.
- `LIVE_TRADING_ENABLED` is still `False`.
- No file named `ibkr_sync.py` exists yet under `src/quantbot/research/portfolio/`.
- No file named `sync_portfolio_ibkr.py` exists yet under `scripts/`.

These are the "design has not silently become implementation" checks. They will continue to pass after V7.2 implementation lands because the implementation tests in `test_ibkr_readonly_sync.py` are a strict superset.

---

## 9. Security note

### Credentials

- **No credentials stored in the repo.** Ever. The V7.2 implementation relies on IBKR's existing TWS / Gateway session — the operator must have already logged in via the IBKR client. The sync script never touches passwords or 2FA codes.
- **No API keys in env vars.** `IBKR_READONLY_ENABLED=1` is a switch, not a credential. The IBKR session is authenticated by TWS/Gateway, not by the script.
- **`.env` / secrets files must not appear.** The V7.2 implementation milestone must NOT introduce a `.env.example` for IBKR credentials. If one ever appears, that is a code review failure.

### Account identifiers

- IBKR account IDs are sensitive (they can be used in social engineering against IBKR support).
- The `account` column written to `positions.csv` must be **redacted by default** — last 4 characters only, e.g. `"...5678"`.
- Operator override: `--account-name-override "MAIN"` replaces the IBKR account id entirely with a friendly local label.
- The `--no-redact-account-id` flag exists for operators who genuinely want the full id stored. It must NOT be the default and must require an explicit acknowledgement.

### Logs

- `ibkr_sync.py` logs use the `quantbot.portfolio.ibkr_sync` logger.
- The wrapper must `try/except` every IBKR call and log **only the error class name**, never the exception message. Exception messages from `ib_insync` sometimes include account ids and contract details.
- No `print(position)` or `print(account)` calls anywhere. Use the logger with explicit formatted messages that never include sensitive fields.

### Committed CSV

- `data/portfolio/positions.csv` may be committed to the operator's local repo. The redaction policy ensures that account ids in committed rows are partial-only.
- The repo's `.gitignore` should explicitly NOT exclude `positions.csv` (the operator may want to commit it) but the V7.2 implementation milestone should add a clear `README` note under `data/portfolio/` reminding the operator that committing real account data is their choice.

### Network

- The IBKR socket connection is to `127.0.0.1` by default. No external host.
- Operator may override the host but this should require `--host` to be set explicitly; the default must not silently accept a non-localhost target.

---

## 10. Path recommendation

The right milestone sequence is:

1. **V7.2 design only (this milestone).** ✅ Now complete.
2. **V7.0.1 launch / mobile access workflow.** A short milestone documenting how to expose the existing Streamlit platform to a phone / tablet on the same LAN. The platform is already local-only; V7.0.1 codifies the safe ways to access it from a mobile device without making the platform publicly reachable. Half a day of writing.
3. **V7.2 implementation.** Only after V7.0.1 lands and the V7.2 design is signed off. The implementation should fit cleanly inside the scaffolding this document specifies. If implementation needs to deviate from the design, the design must be updated FIRST and re-signed.
4. **V7.X future operational milestones.** Examples: V7.8.2 macro cache readers for currencies / commodities; V7.9 daily setup brief generator; V7.10 protection trigger event log (when the V7.7 labels change run-over-run).

### Why V7.0.1 before V7.2 implementation

V7.0.1 is **lower risk and higher leverage**. It makes the existing platform usable from a phone, which compounds the value of every page already built. V7.2 implementation is **higher risk** (a new networked dependency and a new authentication surface) and the value is incremental — operators can already populate positions manually. Doing V7.0.1 first lets the V7.2 design "marinate" while a small, useful milestone lands.

### Decision criteria for proceeding to V7.2 implementation

V7.2 implementation should begin only when **all** of the following hold:

- This design document has been read end-to-end and accepted.
- V7.0.1 launch / mobile workflow has shipped.
- The operator has a paper IBKR account ready to test against.
- The operator has confirmed they want `ib_insync` added as a dependency (this is the only new third-party package in the project so far).
- A code review of the V7.2 implementation will explicitly grep for every forbidden token in Section 5 before merge.

If any of those is missing, V7.2 implementation is deferred. The design document stays as-is.

---

## References

- V7.1 portfolio schema: `src/quantbot/research/portfolio/schema.py`
- V7.1 readers + append helpers: `src/quantbot/research/portfolio/readers.py`
- V7.1 populate script (the template V7.2 implementation will follow): `scripts/populate_portfolio.py`
- V7.7 Protection engine (consumes positions; will consume IBKR-sourced rows transparently): `src/quantbot/research/protection/engine.py`
- V7.4 PortTech engine (same): `src/quantbot/research/porttech/engine.py`
- V7.0 platform: `apps/portfolio_platform.py`
- Project guardrails: `src/quantbot/__init__.py` (`LIVE_TRADING_ENABLED = False`)
- Project research methodology: user memory `feedback_research_methodology` — falsification-first, power-check-before-build, OOS-before-edge, no parameter optimisation. V7.2 is an operational milestone, not a research milestone, but the same discipline applies.

---

**This document defines the conditions under which V7.2 implementation is permitted. Until those conditions are met — and the operator has explicitly accepted both this design AND V7.0.1 — V7.2 remains design-only.**
