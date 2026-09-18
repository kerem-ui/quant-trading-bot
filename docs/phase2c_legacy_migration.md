# Phase 2C: controlled legacy migration and quality audit

## Scope

All work is performed from the Phase 2 checkout. Original legacy inputs are
read-only. No market data, inventories containing local paths, credentials,
databases or generated reports are committed. No provider subscription or
trading feature is added.

The migration reuses the verified Phase 2B schema, DataStore, source/dataset
manifests and checksum validation without editing those modules. Dependency
declarations and the lock are unchanged.

## Inventory first

Run the following from the checkout, supplying your own original repository
location as an argument; no personal path is embedded in code:

```powershell
$env:QUANTBOT_DATA_ROOT = 'C:\QuantData\quant_trading_bot'
$Python = 'C:\QuantEnvs\quant_trading_bot_phase2\Scripts\python.exe'
$LegacyRoot = Read-Host 'Original legacy project directory (read-only)'
& $Python scripts/migrate_legacy_options.py inventory --legacy-root $LegacyRoot --audit-name phase2c_inventory
& $Python scripts/migrate_legacy_options.py migrate --inventory "$env:QUANTBOT_DATA_ROOT\audits\phase2c_inventory\inventory.private.json"
```

An inventory destination must be new. The inventory walks data, reports and
other CSV/gzip/Parquet/database paths, pruning environments, Git internals and
reproducible caches. It records exact size, SHA-256, modification time, file
type, original/relative path, classification, and practical tabular counts,
symbols and coverage. Non-tabular files have a null row count, not a fabricated
count. Inspection failures are explicit.

- inventory.private.json: absolute original paths; external local artifact only.
- inventory.json: sealed portable relative-path inventory.
- inventory.md: human-readable complete table, stored externally.

The migration verifies private/portable inventory agreement, source checksums
before reading, exact copied bytes, output checksums, and every inventoried
original's checksum/mtime again before certifying the corpus.

The discovered local corpus comprised 1,133 files / 271,856,089 bytes. The
backtest processed subset contains exactly 1,248,482 rows in 14 monthly files:
SPY 2022 1,107,526; SPY January 2023 75,568; QQQ January 2022 65,388.
Daily EOD and Greek-enriched versions are additional legacy snapshots; they
must not be described as original provider responses or silently merged.

Selection is explicit: only SPY/QQQ processed monthly CSV.gz and Theta-derived
daily CSV.gz for the bounded period are migrated. Synthetic inputs, generated
reports, features, equity/SEC/macro caches and manual portfolio inputs are
inventoried but are not silently added to the real options corpus.
Guardrails reject over 6 million versioned rows, 512 MB selected compressed
sources, or 60 logical monthly groups; unexpected scale requires review.

## Versioned and duplicate observations

There are three distinct logical series:

- processed: the monthly corpus consumed by existing research/backtests;
- daily_eod: earlier daily normalized EOD snapshots;
- daily_greeks: separately enriched daily snapshots.

All 596 selected source files, representing 4,059,312 versioned rows, are
preserved. These are not 4 million independent market observations.
The combined report separately computes distinct
underlying/observation-date/expiration/strike/right keys and overlapping
snapshots' quote differences.

Preflight found 337,722 excess duplicate observation keys in four daily EOD
months. No duplicate rows are removed. Phase 2B continues to reject duplicate
keys inside a normalized dataset. Migration instead assigns a deterministic
occurrence number within each original key in sorted file/source-row order.
Each occurrence is stored in a separate monthly snapshot. This is a storage
provenance label, never an invented contract or event timestamp. All occurrences
are included by the corpus query view; repeated keys retain a
legacy_duplicate_observation quality flag.

The physical dataset identifier is compact for Windows path limits:
p.SPY.202201.0, e.SPY.202205.1, etc. p/e/g means processed/EOD/Greeks; the
complete series, underlying, month and occurrence are recorded in manifests.
Partitions are monthly batches, never individual option contracts.

## Source and field preservation

Copies use Phase 2B's imports/normalized area with kind=legacy_normalized.
The original gzip bytes are retained as payload.bin; copied/source SHA-256
must match. Normalization parses these verified bytes in memory, rather than
re-reading the original file after checksum verification.

Every recoverable schema field is independently reconciled after Parquet
readback: underlying, date, expiration, exact decimal strike, right, quotes,
supplied last/trade fields, volume, IV, Greeks, spot, available timezone-aware
timestamps and legacy contract terms.

A clearly labeled forensic Parquet sidecar retains every original CSV column
under a legacy_ prefix, with source_file, source_row and source_occurrence.
It includes the original mid/DTE/moneyness/other derived fields and unreliable
OI, without representing them as freshly validated market observations.
Original gzip bytes remain the authority for original text formatting.

Deliberate semantics:

- ALL OI from this affected legacy path becomes null, including nonzero
  values if encountered. No true/false zero classification is guessed.
  legacy_oi_unreliable is recorded; old values survive only in source/forensics.
- Missing event/provider-created/trade timestamps remain null. A stored date
  does not become an invented midnight quote timestamp.
- retrieved_at is explicitly the new import receipt time, not the original
  provider retrieval time. The latter is unavailable.
- Existing multiplier=100 and exercise_style=american are retained exactly
  but flagged legacy_contract_terms_unverified: old normalizers supplied defaults.
- Legacy date values are preserved and flagged unverified because earlier
  normalizers collapsed timestamps, sometimes using last_trade.
- Original provider request bounds are unknown. The dataset requested_range
  is explicitly labeled as migration calendar-month bounds.

Suspicious finite quotes are retained and flagged. Non-finite values, invalid
identities, unsupported source fields, ambiguous timestamps or inconsistent
source/output values produce explicit failures with the source audit retained.
The migration does not weaken the normalized schema to admit invalid rows.

## Reports and corpus manifest

Each monthly logical dataset gets machine-readable JSON and Markdown reports:
row counts, dates, coverage, calls/puts, expirations, DTE distribution,
date/expiry/right strike coverage, duplicate keys and exact duplicates,
missing quotes, zero/negative/crossed quotes, missing IV/Greeks/spot, unreliable
OI, numeric missingness/infinities, timestamp ambiguity, invalid identities,
inconsistent DTE and expected session gaps. No rows are filtered to improve
statistics.

The calendar is deliberately scoped to 2022 and January 2023. It excludes the
documented exchange holidays, includes early-close sessions, and rejects
unsupported periods. It has 251 sessions for 2022 and 20 for January 2023.
References: [NYSE 2022 calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2022_Yearly_Trading_Calendar.pdf)
and [NYSE 2023 calendar](https://www.nyse.com/publicdocs/ICE_NYSE_2023_Yearly_Trading_Calendar.pdf).
Calendar coverage does not establish that every strike/expiry or quote exists.

The top-level manifest under corpora/legacy_options/<corpus-version> references:

- exact inventory checksum and private-path-index checksum;
- normalization version and Git/lock identities;
- all partition dataset manifests and source-copy checksums;
- every quality report and forensic sidecar;
- per-series and total counts, unique observation keys and known limitations;
- row/field/identity/date reconciliation evidence;
- verification that every inventoried original retained its SHA-256 and mtime.

Repeated migration with the same inventory/code is deterministic and uses
write-once content-addressed artifacts. Different code or import inventory
produces a separately identifiable version, never overwrites an old corpus.

## DuckDB checks

The corpus query tool verifies Parquet checksums, then queries local files:

1. Full processed SPY chain on its first available date.
2. One selected call contract across all available dates.
3. Options within 1% of underlying spot on the selected date.
4. Missing-IV counts by underlying.
5. Date/expiration coverage.
6. Total versioned records versus unique observation keys.
7. EOD/Greek keys absent from the processed corpus and differing bid/ask values.

Full query results are external Parquet artifacts; summary counts and the
selected date/contract are in the corpus manifest and quality reports.
Inspection selections are not strategy signals.

## Testing and limitations

tests/test_phase2c_legacy_migration.py tests immutable originals, copy checksums,
OI semantics, field/date/identity preservation, nullable roundtrips, statistics,
safe repetition, version overlap, separate duplicate occurrences, inventory
classification and the bounded calendar. Existing Phase 1 and Phase 2B tests
remain unchanged. Full-suite and dependency checks are run before publication.

No Theta Terminal listener was available on the configured local v3 port during
this phase. Live-provider validation is deferred, not a migration failure.
Existing Phase 2B tests still verify exact future response-byte capture and
separate metadata/timestamps using controlled responses. No historical request
or new subscription was initiated.

Limitations remain: legacy timestamps and trustworthy historical OI cannot be
recovered, provider defaults are not verified contract-reference data, snapshots
can differ, and this is a bounded archive rather than complete options history.
No backtest engine automatically switches to these migrated inputs.
