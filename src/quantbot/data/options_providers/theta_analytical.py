"""Loss-preserving Theta v3 parsing for the new analytical store, without I/O.

Provider payloads are preserved separately before this transformation. Unknown
provider fields remain in that payload. No legacy date/strike/default shortcuts
are applied here and this module does not change the backtest chain interface.
"""
from __future__ import annotations
from datetime import date, datetime
import math
from numbers import Real

import pandas as pd

from ..storage.schemas import normalized_table

def _present(value):
    return value is not None and not (isinstance(value, Real) and math.isnan(value))

def _time(value, source_timezone):
    if not _present(value):
        return None
    ts = pd.Timestamp(value)
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        if not source_timezone:
            raise ValueError("naive provider timestamp requires source timezone")
        ts = ts.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
    return ts.tz_convert("UTC")

def _date(value):
    if type(value) is date:
        return value
    if not isinstance(value, str):
        raise ValueError("date must be an explicit ISO date string")
    return date.fromisoformat(value)

def _flatten(payload):
    response = payload.get("response", []) if isinstance(payload, dict) else payload
    if not isinstance(response, list):
        raise ValueError("expected Theta v3 JSON rows")
    for entry in response:
        if not isinstance(entry, dict):
            raise ValueError("unsupported provider shape; preserve raw and investigate")
        if "data" in entry:
            contract = entry.get("contract", {})
            for tick in entry["data"]:
                if not isinstance(tick, dict):
                    raise ValueError("unsupported provider tick shape")
                conflicts = [k for k in contract if k in tick and tick[k] != contract[k]]
                if conflicts:
                    raise ValueError("conflicting provider contract identity")
                yield contract | tick
        else:
            yield entry

def normalize_payload(payload, *, retrieved_at: datetime,
                      source_timezone: str | None = None,
                      observation_date: date | None = None):
    """Normalize v3 JSON with explicit dates and separate time meanings.

    Observation date must come from an explicit date, caller-supplied EOD date,
    or event timestamp interpreted in the caller-declared exchange timezone.
    last_trade and created never substitute for an observation date.
    """
    output = []
    for row in _flatten(payload):
        event = _time(row.get("timestamp"), source_timezone)
        day = row.get("date")
        if day is not None:
            day = _date(day)
        elif observation_date is not None:
            day = _date(observation_date)
        elif event is not None and source_timezone:
            day = event.tz_convert(source_timezone).date()
        else:
            raise ValueError("explicit observation date or dated event required")
        if event is not None and source_timezone and event.tz_convert(source_timezone).date() != day:
            raise ValueError("observation date disagrees with event date in source timezone")
        identities = [row[k] for k in ("symbol", "underlying", "root") if _present(row.get(k))]
        if not identities or len(set(identities)) != 1:
            raise ValueError("missing or conflicting underlying identity")
        right = row.get("right")
        if right not in ("call", "put", "C", "P", "CALL", "PUT"):
            raise ValueError("invalid option right")
        out = dict(underlying=identities[0], expiration=_date(row.get("expiration")),
            strike=row.get("strike"), right={"C":"call","P":"put"}.get(right, right.lower()),
            observation_date=day, event_timestamp=event, retrieved_at=retrieved_at,
            provider_created_at=_time(row.get("created"), source_timezone),
            trade_timestamp=_time(row.get("last_trade"), source_timezone),
            underlying_timestamp=_time(row.get("underlying_timestamp"), source_timezone),
            quality_flags=[])
        aliases = {
            "multiplier": "multiplier", "exercise_style":"exercise_style",
            "settlement_type":"settlement_type", "provider_contract_id":"contract_symbol",
            "implied_volatility":"implied_vol", "trade_count":"count",
            "provider_status":"status",
        }
        for name in ("bid", "ask", "last", "trade_price", "trade_size", "open", "high",
                     "low", "close", "bid_size", "ask_size", "volume", "open_interest",
                     "delta", "gamma", "theta", "vega", "rho", "underlying_price", "iv_error",
                     "bid_exchange", "ask_exchange", "bid_condition", "ask_condition"):
            aliases[name] = name
        for target, origin in aliases.items():
            value = row.get(origin)
            if not _present(value):
                value = None
            if target.endswith(("_exchange", "_condition")) and value is not None:
                value = str(value)
            out[target] = value
        if out["implied_volatility"] is not None and not 0 < out["implied_volatility"] <= 5:
            out["quality_flags"].append("suspect_iv")
        output.append(out)
    return normalized_table(output, "options-v1")



def ingest_payload(store, payload: bytes, *, retrieved_at: datetime, request: dict,
                   requested_start: date, requested_end: date,
                   source_timezone: str | None = None,
                   observation_date: date | None = None,
                   kind: str = "provider_payload"):
    """Preserve JSON source, normalize, validate and publish one bounded batch.

    No network operation is performed. For undated EOD responses use a
    single-day request with an explicit observation_date; do not guess from
    a stale last trade or provider creation time.
    """
    import json
    policy = {"source_timezone": source_timezone,
              "observation_date_policy": "explicit-or-event",
              "observation_date": observation_date.isoformat() if observation_date else None}
    source = store.preserve_source(payload, provider="thetadata",
        dataset="options_eod", kind=kind, retrieved_at=retrieved_at, request=request)
    table = normalize_payload(json.loads(payload), retrieved_at=retrieved_at,
        source_timezone=source_timezone, observation_date=observation_date)
    return store.write_dataset(table, schema_name="options-v1", provider="thetadata",
        dataset="options_eod", sources=[source], requested_start=requested_start,
        requested_end=requested_end, normalization_version="theta-v3-1",
        normalization_parameters=policy)
