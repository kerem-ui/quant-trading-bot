# Phase 4C readiness: preregistered, data acquisition blocked

The preregistration and integrity checks are complete. The expanded research
experiment is **not complete**. The local Theta v3 endpoint remains unreachable,
including an unsandboxed recheck. No new market data was requested or downloaded.
No validation, holdout, cost-sensitivity or symbol/year performance was evaluated.
No new research classification is justified and Phase 4C acceptance is not met.

Start the existing authenticated Theta v3 Terminal to allow a bounded access
check after publication. Do not send account secrets. Current subscription/tier
cannot be determined while Terminal is unavailable. The public documentation
lists Standard for the required daily IV/Greek endpoint and history sufficient
for January2022 onward; that does not establish current account entitlement.
No paid upgrade, Pro subscription, alternate provider, OI purchase or intraday
subscription is currently justified. SPY-only remains a partial experiment and
cannot fulfill the multi-symbol acceptance criterion.

The complete design, official provider references, requested coverage, known
history limitations and measured storage proxy are in `phase4c_research_plan.md`.
The machine-readable registration and readiness records are under
`research/phase4c/s05-v1/`. Existing S05 parameters and specification bytes are
unchanged. Future acquisition/run code must enforce and test the registered
publication and validation-seal gates before resuming; this checkpoint does not
pretend that an unimplemented runner has been certified.

## Verification

| Check | Result |
|---|---|
| New Phase4C registration tests |14 passed|
| Phase4A analytics (included in full suite) |72 passed|
| Phase4B strategy/report guards |52 passed|
| Phase1 ETF/options/risk regressions |178 passed|
| Phase2 storage/provenance/migration |62 passed|
| Phase3 market/execution/research |111 passed|
| Full project suite |1696 passed;14 skipped;0 failures;0 errors;0 warnings|
| Full-suite elapsed time |581.51 seconds|
| Offline lock check |72 packages resolved;passed|
| Installed dependency consistency |72 packages;all compatible|
| Locked offline environment dry-run |Would make no changes|

The 14 skips are unchanged optional SEC-cache derivations: AI5, energy4,
semiconductors5. They are unrelated to S05 or the missing Theta Terminal.
Python remains3.12.10 and uv0.11.8. No dependency or environment changes occurred.

Tests were written before registration:1 failure and13 setup errors reported
missing `preregistration.json`. All14 passed after it was created, without
weakening assertions. A Git attribute inspection additionally found the new
sealed JSON initially lacked an explicit LF convention; the existing convention
was extended to Phase4C and verified as `eol: lf`, preserving portable byte hashes.

Full test logs and JUnit are ignored under
`runs/phase4c/preregistration-verification/`; their hashes are in `readiness.json`.
The counts above are selections from the single full run, not duplicate test runs.

## Changed files

- `.gitattributes`: LF preservation for Phase4C sealed JSON only.
- `research/phase4c/s05-v1/preregistration.json`: sealed pre-performance protocol.
- `research/phase4c/s05-v1/readiness.json`: small verification/blocker metadata.
- `docs/phase4c_research_plan.md`: readable protocol, evidence and data requirements.
- `docs/phase4c_readiness.md`: this status and verification report.
- `tests/test_phase4c_preregistration.py`:14 deterministic registration checks.

No production source, existing test, strategy configuration, dependency lock,
market-data file, generated research ledger or prior documentation was changed.
Original OneDrive files were not written. New test logs remain ignored, as do
market Parquet/database files, local data, virtual environments and `.env`.
No Phase5 work has begun.