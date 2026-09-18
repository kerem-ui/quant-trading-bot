"""Strict typed analytical schemas, independent of provider parsing and fills."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
import hashlib
import math
from numbers import Real
import re

import pyarrow as pa

UTC = pa.timestamp("ns", tz="UTC")
PRICE = pa.float64()
STRIKE = pa.decimal128(20, 6)

def _field(name, dtype, required=False):
    return pa.field(name, dtype, nullable=not required)

_COMMON = [
    _field("observation_date", pa.date32(), True),
    _field("event_timestamp", UTC),
    _field("provider_created_at", UTC),
    _field("retrieved_at", UTC, True),
    _field("quality_flags", pa.list_(pa.string()), True),
]
OPTIONS = pa.schema([
    _field("underlying", pa.string(), True),
    _field("contract_id", pa.string(), True),
    _field("provider_contract_id", pa.string()),
    _field("expiration", pa.date32(), True),
    _field("strike", STRIKE, True),
    _field("right", pa.string(), True),
    _field("multiplier", pa.int64()),
    _field("exercise_style", pa.string()),
    _field("settlement_type", pa.string()),
    *_COMMON,
    _field("trade_timestamp", UTC),
    _field("underlying_timestamp", UTC),
    *[_field(n, PRICE) for n in (
        "bid", "ask", "last", "trade_price", "open", "high", "low", "close",
        "implied_volatility", "delta", "gamma", "theta", "vega", "rho",
        "underlying_price", "iv_error")],
    *[_field(n, pa.int64()) for n in (
        "bid_size", "ask_size", "trade_size", "volume", "open_interest", "trade_count")],
    *[_field(n, pa.string()) for n in (
        "bid_exchange", "ask_exchange", "bid_condition", "ask_condition", "provider_status")],
], metadata={b"schema_name": b"options-v1"})

EQUITIES = pa.schema([
    _field("symbol", pa.string(), True), *_COMMON,
    *[_field(n, PRICE) for n in (
        "raw_open", "raw_high", "raw_low", "raw_close",
        "adjusted_open", "adjusted_high", "adjusted_low", "adjusted_close",
        "adjustment_factor", "dividends", "split_ratio")],
    _field("adjustment_convention", pa.string()),
    _field("volume", pa.int64()),
], metadata={b"schema_name": b"equities-v1"})

SCHEMAS = {"options-v1": OPTIONS, "equities-v1": EQUITIES}
SORT_KEYS = {
    "options-v1": ["observation_date", "underlying", "contract_id", "event_timestamp"],
    "equities-v1": ["observation_date", "symbol"],
}

def contract_identity(row: dict) -> str:
    """Internal composite ID, not an invented OCC/provider symbol."""
    parts = [str(row.get(k)) for k in (
        "underlying", "expiration", "right", "strike", "multiplier",
        "provider_contract_id", "exercise_style", "settlement_type")]
    return "composite:" + hashlib.sha256("|".join(parts).encode()).hexdigest()

def _value(value, field):
    if value is None:
        if not field.nullable:
            raise ValueError(f"required field {field.name} is null")
        return None
    t = field.type
    if pa.types.is_string(t):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field.name} must be a nonempty string")
    elif pa.types.is_integer(t):
        if isinstance(value, bool) or not isinstance(value, (int,)):
            raise ValueError(f"{field.name} must be an integer, not a coerced value")
    elif pa.types.is_floating(t) or pa.types.is_decimal(t):
        if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
            raise ValueError(f"{field.name} must be numeric")
        if not math.isfinite(value):
            raise ValueError(f"{field.name} must be finite or null")
        if pa.types.is_decimal(t):
            exact = Decimal(str(value))
            value = exact.quantize(Decimal("0.000001"))
            if value != exact:
                raise ValueError(f"{field.name} exceeds six decimal places")
        else:
            value = float(value)
    elif pa.types.is_date(t):
        if not isinstance(value, date) or isinstance(value, datetime):
            raise ValueError(f"{field.name} must be a date without time")
    elif pa.types.is_timestamp(t):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{field.name} requires a timezone-aware datetime")
    elif pa.types.is_list(t):
        if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
            raise ValueError(f"{field.name} must be a list of strings")
        value = sorted(set(value))
    return value

def normalized_table(rows, schema_name: str) -> pa.Table:
    """Validate values without silent casting, fill only nullable fields, sort."""
    schema = SCHEMAS[schema_name]
    if isinstance(rows, pa.Table):
        if not rows.schema.equals(schema, check_metadata=True):
            raise ValueError(f"schema mismatch: expected {schema_name}")
        rows = rows.to_pylist()
    output, identities = [], set()
    for source in rows:
        unknown = set(source) - set(schema.names)
        if unknown:
            raise ValueError(f"unknown normalized fields: {sorted(unknown)}")
        row = dict(source)
        row.setdefault("quality_flags", [])
        if schema_name == "options-v1":
            # Validate identity before generating the canonical identifier.
            for name in ("underlying", "expiration", "right", "strike"):
                row[name] = _value(row.get(name), schema.field(name))
            if row["right"] not in ("call", "put") or row["strike"] <= 0:
                raise ValueError("invalid right or strike")
            row.setdefault("contract_id", contract_identity(row))
        row = {f.name: _value(row.get(f.name), f) for f in schema}
        symbol = row["underlying" if schema_name == "options-v1" else "symbol"]
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9._^-]*", symbol):
            raise ValueError("invalid underlying/symbol identity")
        flags = set(row["quality_flags"])
        if schema_name == "options-v1":
            if row["contract_id"] != contract_identity(row):
                raise ValueError("contract identity mismatch")
            if row["expiration"] < row["observation_date"]:
                raise ValueError("observation is after contract expiration")
            if row["multiplier"] is not None and row["multiplier"] <= 0:
                raise ValueError("multiplier must be positive or null")
            if row["bid"] is None or row["ask"] is None:
                flags.add("missing_quote")
            elif row["bid"] > row["ask"]:
                flags.add("crossed_quote")
            if any(row[n] is not None and row[n] < 0 for n in ("bid", "ask")):
                flags.add("negative_quote")
            if row["open_interest"] is None:
                flags.add("missing_open_interest")
            if row["multiplier"] is None:
                flags.add("unknown_multiplier")
        else:
            if any(row["adjusted_"+n] is not None for n in ("open","high","low","close")):
                if row["adjustment_convention"] not in ("adjusted_over_raw", "provider_adjusted"):
                    raise ValueError("adjustment convention required for adjusted prices")
            factor = row["adjustment_factor"]
            if factor is not None:
                if factor <= 0 or row["adjustment_convention"] != "adjusted_over_raw":
                    raise ValueError("invalid adjustment convention or factor")
                for n in ("open", "high", "low", "close"):
                    raw, adjusted = row["raw_"+n], row["adjusted_"+n]
                    if raw is not None and adjusted is not None and not math.isclose(
                            raw * factor, adjusted, rel_tol=1e-9, abs_tol=1e-9):
                        raise ValueError("adjustment factor inconsistent with prices")
            if row["raw_close"] is None and row["adjusted_close"] is None:
                raise ValueError("equity requires at least one explicitly named close basis")
            for basis in ("raw_", "adjusted_"):
                values = [row[basis+n] for n in ("open", "high", "low", "close")]
                if any(v is not None and v <= 0 for v in values):
                    raise ValueError("equity prices must be positive or null")
                op, hi, lo, cl = values
                if hi is not None and lo is not None and hi < lo:
                    raise ValueError("invalid equity high/low")
                if any(v is not None and ((hi is not None and v > hi) or
                       (lo is not None and v < lo)) for v in (op, cl)):
                    raise ValueError("equity OHLC outside high/low")
        for f in schema:
            if pa.types.is_integer(f.type) and row[f.name] is not None and row[f.name] < 0:
                raise ValueError(f"{f.name} cannot be negative")
        row["quality_flags"] = sorted(flags)
        identity = tuple(row[k] for k in SORT_KEYS[schema_name])
        if identity in identities:
            raise ValueError(f"duplicate observation identity: {identity}")
        identities.add(identity)
        output.append(row)
    table = pa.Table.from_pylist(output, schema=schema)
    return table.sort_by([(k, "ascending") for k in SORT_KEYS[schema_name]])
