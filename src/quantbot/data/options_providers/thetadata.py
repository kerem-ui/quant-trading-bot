"""ThetaData historical options adapter (Theta Terminal **v3**).

This adapter integrates ThetaData's *historical* options endpoints via the
local Theta Terminal (default ``http://127.0.0.1:25503``, API **v3**). It
does **NOT**:
  - place orders or connect to any broker,
  - subscribe to live market data,
  - hard-code, log, or print credentials,
  - perform a real fetch unless ``dry_run=False`` is explicitly chosen.

Authentication
--------------
When the base URL points at a **local Theta Terminal** (``127.0.0.1`` /
``localhost``), Terminal authentication is handled out-of-band by the user's
``creds.txt`` next to the Terminal jar - this module never touches creds.txt.
For a non-local base URL we still allow ``THETADATA_API_KEY`` from the env
(masked everywhere). No credential value is ever written to disk by this code.

We use Python stdlib ``urllib.request`` only - no new packages.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from ..options_chain_loader import (
    OptionsChainLoader,
    REQUIRED_COLS,
    add_derived_columns,
    register_loader,
)
from ..options_providers.synthetic import SyntheticOptionsLoader


def _mask(value: str | None, keep: int = 4) -> str:
    if not value:
        return "<unset>"
    if len(value) <= keep + 2:
        return "***"
    return value[:2] + "***" + value[-keep:]


# --------------------------------------------------------------------------- #
# ThetaData -> canonical field mapping
# --------------------------------------------------------------------------- #
# In ThetaData v3 the option/history/eod response is a FLAT array of rows
# with these fields:
#   symbol, expiration (YYYY-MM-DD), strike (dollars), right ("call"/"put"),
#   created (ISO datetime), last_trade (ISO datetime),
#   open, high, low, close, volume, count,
#   bid_size, bid_exchange, bid, bid_condition,
#   ask_size, ask_exchange, ask, ask_condition.
# IV and Greeks are NOT in the EOD response - they need separate endpoints.
def _norm_strike(x) -> float:
    """Strike in v3 is already in dollars; v2 used int*1000 - handle both."""
    if pd.isna(x):
        return float("nan")
    v = float(x)
    return v / 1000.0 if v > 10_000 else v


def _norm_expiration(x) -> pd.Timestamp:
    """Accept both v2 (YYYYMMDD int/str) and v3 (YYYY-MM-DD string) formats.

    pd.to_datetime on a bare int parses it as nanoseconds since the epoch
    (giving 1970-01-01 + tiny offset), so we detect 8-digit YYYYMMDD values
    explicitly first.
    """
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return pd.NaT
    if isinstance(x, (int, np.integer)) or (
        isinstance(x, str) and x.isdigit() and len(x) == 8
    ):
        return pd.to_datetime(str(int(x)), format="%Y%m%d", errors="coerce")
    return pd.to_datetime(x, errors="coerce")


_RIGHT_MAP = {"C": "call", "P": "put", "c": "call", "p": "put",
              "CALL": "call", "PUT": "put", "call": "call", "put": "put"}


def _col(df: pd.DataFrame, name: str, default=np.nan) -> pd.Series:
    """Return ``df[name]`` if present, otherwise a default-filled Series of
    the right length. Avoids the scalar-vs-Series trap of ``df.get(...)``."""
    if name in df.columns:
        return df[name]
    return pd.Series([default] * len(df), index=df.index)


def normalize_thetadata_eod(
    rows: Iterable[dict],
    *,
    underlying: str,
    snapshot_date: str | pd.Timestamp,
    spot: float,
    contract_multiplier: int = 100,
    exercise_style: str = "american",
) -> pd.DataFrame:
    """Pure mapping function (no I/O) - turn a ThetaData EOD bulk response
    into the canonical schema. Unit-testable without any network access."""
    snapshot_date = pd.Timestamp(snapshot_date).normalize()
    df = pd.DataFrame(list(rows))
    if df.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLS))

    # ThetaData uses 'exp' or 'expiration'; 'right' or 'option_type'; 'iv' or
    # 'implied_volatility' - prefer the explicit canonical name when present.
    exp_src = df["expiration"] if "expiration" in df.columns else _col(df, "exp")
    type_src = df["option_type"] if "option_type" in df.columns else _col(df, "right", "C")
    iv_src = df["implied_volatility"] if "implied_volatility" in df.columns else _col(df, "iv")

    out = pd.DataFrame(index=df.index)
    out["date"] = pd.Series([snapshot_date] * len(df), index=df.index)
    out["underlying"] = underlying.upper()
    out["expiration"] = exp_src.map(_norm_expiration)
    out["dte"] = (out["expiration"] - snapshot_date).dt.days.astype("Int64")
    out["option_type"] = type_src.astype(str).map(_RIGHT_MAP).fillna("call")
    out["strike"] = df["strike"].map(_norm_strike).astype(float)
    out["bid"] = df["bid"].astype(float)
    out["ask"] = df["ask"].astype(float)
    out["mid"] = (out["bid"] + out["ask"]) / 2.0
    out["volume"] = _col(df, "volume", 0).fillna(0).astype("Int64")
    out["open_interest"] = _col(df, "open_interest", 0).fillna(0).astype("Int64")
    out["implied_volatility"] = iv_src.astype(float)
    for g in ("delta", "gamma", "theta", "vega"):
        out[g] = _col(df, g).astype(float)
    out["underlying_price"] = float(spot)
    out["contract_multiplier"] = int(contract_multiplier)
    out["exercise_style"] = exercise_style
    out["last"] = _col(df, "last").astype(float)
    out["rho"] = _col(df, "rho").astype(float)
    out = out[list(REQUIRED_COLS) + ["last", "rho"]]
    return add_derived_columns(out)


def normalize_thetadata_v3_option_eod(
    rows: Iterable[dict] | pd.DataFrame,
    *,
    underlying: str,
    spot_by_date: dict[pd.Timestamp, float],
    contract_multiplier: int = 100,
    exercise_style: str = "american",
) -> pd.DataFrame:
    """Normalize a v3 ``/v3/option/history/eod`` flat response into canonical.

    Each input row covers ONE (date, expiration, strike, right). The row's
    date is parsed from ``last_trade`` (falling back to ``created``). IV and
    Greeks are not in the EOD response - left as NaN; the validator warns
    rather than errors on missing IV.
    """
    df = (rows.copy() if isinstance(rows, pd.DataFrame)
          else pd.DataFrame(list(rows)))
    if df.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLS))

    # Date per row.
    date_series = None
    for col in ("last_trade", "created"):
        if col in df.columns:
            date_series = pd.to_datetime(df[col], errors="coerce", utc=True
                                          ).dt.tz_convert(None).dt.normalize()
            break
    if date_series is None:
        raise ValueError(
            "v3 option/history/eod response is missing both 'last_trade' "
            "and 'created' - cannot determine row date."
        )

    out = pd.DataFrame(index=df.index)
    out["date"] = date_series
    out["underlying"] = underlying.upper()
    out["expiration"] = df["expiration"].map(_norm_expiration)
    out["dte"] = (out["expiration"] - out["date"]).dt.days.astype("Int64")
    out["option_type"] = (df["right"].astype(str).str.lower()
                          .map(_RIGHT_MAP).fillna("call"))
    out["strike"] = df["strike"].astype(float).map(_norm_strike)
    out["bid"] = df["bid"].astype(float)
    out["ask"] = df["ask"].astype(float)
    out["mid"] = (out["bid"] + out["ask"]) / 2.0
    out["volume"] = _col(df, "volume", 0).fillna(0).astype("Int64")
    out["open_interest"] = _col(df, "open_interest", 0).fillna(0).astype("Int64")
    out["implied_volatility"] = _col(df, "implied_volatility").astype(float)
    for g in ("delta", "gamma", "theta", "vega"):
        out[g] = _col(df, g).astype(float)
    out["underlying_price"] = out["date"].map(spot_by_date).astype(float)
    out["contract_multiplier"] = int(contract_multiplier)
    out["exercise_style"] = exercise_style
    out["last"] = _col(df, "close").astype(float)   # EOD close is the 'last'
    out["rho"] = _col(df, "rho").astype(float)
    out = out[list(REQUIRED_COLS) + ["last", "rho"]]
    return add_derived_columns(out)


def normalize_thetadata_v3_greeks_eod(
    rows: Iterable[dict] | pd.DataFrame,
    *,
    underlying: str,
    spot_by_date: dict[pd.Timestamp, float] | None = None,
    contract_multiplier: int = 100,
    exercise_style: str = "american",
) -> pd.DataFrame:
    """Normalize a v3 ``/v3/option/history/greeks/eod`` flat response.

    Maps ``implied_vol`` -> ``implied_volatility``; takes ``delta`` /
    ``gamma`` / ``theta`` / ``vega`` / ``rho`` directly from the row;
    pulls ``underlying_price`` from the row (this endpoint includes it).
    ``spot_by_date`` is an optional fallback for rows where the row's spot
    is missing or 0.0. Higher-order Greeks (charm, vanna, etc.) and
    ``iv_error`` are dropped to keep the canonical schema lean (they remain
    in the raw cache).
    """
    df = (rows.copy() if isinstance(rows, pd.DataFrame)
          else pd.DataFrame(list(rows)))
    if df.empty:
        return pd.DataFrame(columns=list(REQUIRED_COLS))

    date_series = None
    for col in ("last_trade", "created", "timestamp", "underlying_timestamp"):
        if col in df.columns:
            date_series = pd.to_datetime(df[col], errors="coerce", utc=True
                                          ).dt.tz_convert(None).dt.normalize()
            break
    if date_series is None:
        raise ValueError(
            "v3 greeks/eod response missing all of "
            "{last_trade, created, timestamp, underlying_timestamp}."
        )

    out = pd.DataFrame(index=df.index)
    out["date"] = date_series
    out["underlying"] = underlying.upper()
    out["expiration"] = df["expiration"].map(_norm_expiration)
    out["dte"] = (out["expiration"] - out["date"]).dt.days.astype("Int64")
    out["option_type"] = (df["right"].astype(str).str.lower()
                          .map(_RIGHT_MAP).fillna("call"))
    out["strike"] = df["strike"].astype(float).map(_norm_strike)
    out["bid"] = df["bid"].astype(float)
    out["ask"] = df["ask"].astype(float)
    out["mid"] = (out["bid"] + out["ask"]) / 2.0
    out["volume"] = _col(df, "volume", 0).fillna(0).astype("Int64")
    out["open_interest"] = _col(df, "open_interest", 0).fillna(0).astype("Int64")
    # Greeks straight from provider. ThetaData returns implied_vol = 0.0 when
    # the IV solver fails (typically deep-ITM rows where intrinsic ~= mark
    # and IV is indeterminate). Treat provider-zero as missing so the
    # validator warns rather than erroring (iv <= 0 would otherwise be an
    # error). The provider's iv_error column is preserved in the raw cache.
    iv = _col(df, "implied_vol").astype(float)
    # Mark IV<=0 (solver failure, typically deep-ITM) and IV>5 (numerical
    # wing instability) as missing; both are untrustworthy values that the
    # validator would otherwise hard-reject.
    out["implied_volatility"] = iv.where((iv > 0) & (iv <= 5.0))
    out["delta"] = _col(df, "delta").astype(float)
    out["gamma"] = _col(df, "gamma").astype(float)
    out["theta"] = _col(df, "theta").astype(float)
    out["vega"] = _col(df, "vega").astype(float)
    out["rho"] = _col(df, "rho").astype(float)
    # Underlying price: prefer row value, fall back to spot_by_date map.
    row_spot = _col(df, "underlying_price").astype(float)
    if spot_by_date:
        fb = out["date"].map(spot_by_date).astype(float)
        row_spot = row_spot.where(row_spot > 0, fb)
    out["underlying_price"] = row_spot
    out["contract_multiplier"] = int(contract_multiplier)
    out["exercise_style"] = exercise_style
    out["last"] = _col(df, "close").astype(float)
    out = out[list(REQUIRED_COLS) + ["last", "rho"]]
    return add_derived_columns(out)


# --------------------------------------------------------------------------- #
# Loader class
# --------------------------------------------------------------------------- #
def _is_local_url(url: str) -> bool:
    return ("127.0.0.1" in url) or ("localhost" in url)


def _yyyymmdd(d: pd.Timestamp | str | int) -> int:
    return int(pd.Timestamp(d).strftime("%Y%m%d"))


class ThetaDataLoader(OptionsChainLoader):
    """Historical options-chain loader for Theta Terminal **v3**.

    Defaults to the local Terminal at ``http://127.0.0.1:25503``. With a local
    base URL the Terminal handles authentication via ``creds.txt`` next to its
    jar; this loader never reads or writes that file and never requires an
    env-var key. For a remote base URL, ``THETADATA_API_KEY`` (env var) is
    accepted and **masked** in every log line / repr.

    ``dry_run=True`` (default) routes the entire pipeline through the
    synthetic loader so the adapter can be wired end-to-end without ever
    touching the network. Real fetches occur only when the caller explicitly
    sets ``dry_run=False`` (the sample workflow only does this after the user
    passes ``--approve-real-fetch``).
    """

    name = "thetadata"

    DEFAULT_API_KEY_ENV = "THETADATA_API_KEY"
    DEFAULT_BASE_URL_ENV = "THETADATA_BASE_URL"
    DEFAULT_BASE_URL = "http://127.0.0.1:25503"
    DEFAULT_API_VERSION = "v3"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        api_version: str = DEFAULT_API_VERSION,
        rate_limit_seconds: float = 0.25,
        timeout_seconds: float = 30.0,
        dry_run: bool = True,
        synthetic_seed: int = 42,
    ):
        # Credentials: never stored except as a private attribute, never logged.
        self._api_key = api_key or os.environ.get(self.DEFAULT_API_KEY_ENV)
        self._base_url = (
            (base_url or os.environ.get(self.DEFAULT_BASE_URL_ENV)
             or self.DEFAULT_BASE_URL).rstrip("/")
        )
        self.api_version = str(api_version)
        self.rate_limit_seconds = float(rate_limit_seconds)
        self.timeout_seconds = float(timeout_seconds)
        self.dry_run = bool(dry_run)
        self._dry = SyntheticOptionsLoader(seed=synthetic_seed)
        self._last_call = 0.0

    @property
    def is_local_terminal(self) -> bool:
        return _is_local_url(self._base_url)

    @property
    def has_credentials(self) -> bool:
        """Local Terminal authenticates via creds.txt -> treated as 'has creds'.
        For a remote URL, an env-var key is required."""
        return self.is_local_terminal or bool(self._api_key)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        auth = "local-terminal" if self.is_local_terminal else f"key={_mask(self._api_key)}"
        return (f"<ThetaDataLoader base={self._base_url!r} api={self.api_version} "
                f"{auth} dry_run={self.dry_run}>")

    # ------------------------------------------------------------------ #
    # HTTP helpers (stdlib only - no new packages)
    # ------------------------------------------------------------------ #
    def _url(self, path: str) -> str:
        path = path.lstrip("/")
        if not path.startswith(self.api_version + "/"):
            path = f"{self.api_version}/{path}"
        return f"{self._base_url}/{path}"

    def _get_json(self, path: str, params: dict[str, Any]) -> dict:
        """GET ``path`` with ``params`` and return parsed JSON.

        Rate-limited; honors ``timeout_seconds``. Sends ``Accept:
        application/json``. For remote base URLs adds the masked API key as a
        bearer token; the local Terminal does NOT need it.
        """
        if self.rate_limit_seconds > 0:
            wait = self.rate_limit_seconds - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
        url = self._url(path)
        if params:
            url = url + "?" + urlencode({k: v for k, v in params.items()
                                          if v is not None})
        headers = {"Accept": "application/json"}
        if self._api_key and not self.is_local_terminal:
            headers["Authorization"] = f"Bearer {self._api_key}"
        req = Request(url, headers=headers)
        try:
            with urlopen(req, timeout=self.timeout_seconds) as resp:  # noqa: S310
                body = resp.read()
        except HTTPError as exc:
            raise RuntimeError(
                f"ThetaData HTTP {exc.code} on {path} (params={params}): "
                f"{exc.reason}"
            ) from None
        except URLError as exc:
            raise RuntimeError(
                f"ThetaData URL error on {path}: {exc.reason}. "
                "Is the Theta Terminal running on the configured base URL?"
            ) from None
        finally:
            self._last_call = time.monotonic()
        return json.loads(body)

    # ------------------------------------------------------------------ #
    # v3 endpoint wrappers
    #   * /v3/option/list/expirations?symbol=...
    #   * /v3/stock/history/eod?symbol=...&start_date=...&end_date=...
    #   * /v3/option/history/eod?symbol=...&expiration=*&start_date=...
    #     &end_date=...&max_dte=...  (response: flat array of dicts)
    # All endpoints accept `symbol` (v3) - the old `root` parameter is
    # rejected. Date format is YYYYMMDD or YYYY-MM-DD.
    # ------------------------------------------------------------------ #
    def _stock_history_eod(self, underlying: str, start: pd.Timestamp,
                            end: pd.Timestamp) -> pd.DataFrame:
        """Optional endpoint - **requires a Stocks Value subscription**.

        Not called from :meth:`load` by default. Kept for users whose
        ThetaData plan includes stock history; otherwise the local ETF cache
        provides the underlying spot (see :func:`_spot_from_local_cache`).
        """
        payload = self._get_json("stock/history/eod", {
            "symbol": underlying.upper(),
            "start_date": _yyyymmdd(start),
            "end_date": _yyyymmdd(end),
            "format": "json",
        })
        return _flatten_v3_payload(payload)

    def _option_list_expirations(self, underlying: str) -> list[pd.Timestamp]:
        payload = self._get_json("option/list/expirations", {
            "symbol": underlying.upper(),
            "format": "json",
        })
        df = _flatten_v3_payload(payload)
        if df.empty or "expiration" not in df.columns:
            return []
        out = pd.to_datetime(df["expiration"], errors="coerce").dropna()
        return sorted(set(out.dt.normalize()))

    def _option_history_eod(self, underlying: str, start: pd.Timestamp,
                             end: pd.Timestamp, *,
                             expiration: str = "*",
                             max_dte: int | None = None) -> pd.DataFrame:
        params = {
            "symbol": underlying.upper(),
            "expiration": expiration,
            "start_date": _yyyymmdd(start),
            "end_date": _yyyymmdd(end),
            "format": "json",
        }
        if max_dte is not None:
            params["max_dte"] = int(max_dte)
        payload = self._get_json("option/history/eod", params)
        return _flatten_v3_payload(payload)

    def _option_history_greeks_eod(self, underlying: str, start: pd.Timestamp,
                                    end: pd.Timestamp, *,
                                    expiration: str = "*",
                                    max_dte: int | None = None) -> pd.DataFrame:
        """EOD endpoint enriched with IV + Greeks.

        Verified to work under Options Standard (HTTP 200). Pro-only variant
        ``option/history/greeks/all`` (intraday) is intentionally NOT used.
        Response structure mirrors ``/option/history/eod`` ({"response":[
        {"contract":..., "data":[...]}]}) but each ``data`` row also contains:
        ``implied_vol``, ``delta``, ``gamma``, ``theta``, ``vega``, ``rho``,
        ``iv_error``, ``underlying_price``, plus higher-order Greeks (charm,
        vanna, vomma, ...).  The canonical schema keeps only 1st-order
        Greeks; higher-order are dropped at normalization.
        """
        params = {
            "symbol": underlying.upper(),
            "expiration": expiration,
            "start_date": _yyyymmdd(start),
            "end_date": _yyyymmdd(end),
            "format": "json",
        }
        if max_dte is not None:
            params["max_dte"] = int(max_dte)
        payload = self._get_json("option/history/greeks/eod", params)
        return _flatten_v3_payload(payload)

    # ------------------------------------------------------------------ #
    def load(
        self,
        underlying: str,
        start: str | pd.Timestamp,
        end: str | pd.Timestamp,
        *,
        dte_min: int | None = None,
        dte_max: int | None = None,
        option_type: str | None = None,
        max_expirations: int | None = 6,
    ) -> pd.DataFrame:
        # --- dry-run path (default) ----------------------------------- #
        if self.dry_run:
            df = self._dry.load(underlying, start, end,
                                 dte_min=dte_min, dte_max=dte_max,
                                 option_type=option_type)
            df = df.copy()
            df.attrs["provider"] = "thetadata"
            df.attrs["dry_run"] = True
            return df

        if not self.has_credentials:
            raise RuntimeError(
                "ThetaDataLoader: real fetch requested but no credentials. "
                "For the local Theta Terminal, point base_url at "
                "http://127.0.0.1:25503 (creds.txt handles auth). "
                f"For a remote URL, set {self.DEFAULT_API_KEY_ENV} in the env."
            )

        # --- real fetch (Theta Terminal v3) -------------------------- #
        # ONE HTTP call covers the option chain:
        #   /v3/option/history/eod with expiration=* and max_dte to bound rows
        # The underlying spot is pulled from the LOCAL ETF cache / yfinance
        # (NOT from /v3/stock/history/eod, which requires a Stocks Value
        # subscription).
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        days = pd.bdate_range(start_ts, end_ts)
        if len(days) == 0:
            return pd.DataFrame(columns=list(REQUIRED_COLS))

        spot_by_date = _spot_from_local_cache(underlying, start_ts, end_ts)

        max_dte_effective = (dte_max if dte_max is not None else 60) + 5
        raw = self._option_history_eod(
            underlying, start_ts, end_ts,
            expiration="*", max_dte=max_dte_effective,
        )
        if raw.empty:
            return pd.DataFrame(columns=list(REQUIRED_COLS))

        df = normalize_thetadata_v3_option_eod(
            raw, underlying=underlying, spot_by_date=spot_by_date,
        )
        if option_type:
            df = df[df["option_type"].str.lower() == option_type.lower()]
        if dte_min is not None:
            df = df[df["dte"] >= dte_min]
        if dte_max is not None:
            df = df[df["dte"] <= dte_max]
        df.attrs["provider"] = "thetadata"
        df.attrs["dry_run"] = False
        # max_expirations is kept on the signature for back-compat but is no
        # longer needed: max_dte already bounds the bulk request server-side.
        _ = max_expirations
        return df.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# v3 payload flattener  (defensive against schema drift)
# --------------------------------------------------------------------------- #
def _flatten_v3_payload(
    payload, *,
    contract_fields: tuple[str, ...] | None = ("expiration", "strike", "right", "root"),
) -> pd.DataFrame:
    """Flatten ThetaData v3 historical payloads into a tidy DataFrame.

    Supported shapes (handled defensively):
      v3-FLAT: ``[{...}, {...}]`` - top-level JSON array (default for v3
               history/eod and list/expirations).
      WRAPPED: ``{"response": [{...}, ...]}``
      LEGACY:  ``{"header": {"format": [...]}, "response":
                  [{"contract": {...}, "ticks": [[...]]}, ...]}``
      WRAPPED-MATRIX: ``{"header": {"format": [...]}, "response": [[...]]}``
    """
    # v3-FLAT (top-level list).
    if isinstance(payload, list):
        if not payload:
            return pd.DataFrame()
        return pd.DataFrame(payload)

    if not isinstance(payload, dict):
        return pd.DataFrame()
    resp = payload.get("response") or []
    if not resp:
        return pd.DataFrame()
    fmt = (payload.get("header") or {}).get("format")

    # Shape C: each response item is already a flat record (no nested
    # ticks/data list to expand). E.g. /v3/option/list/expirations.
    if isinstance(resp[0], dict) and "ticks" not in resp[0] and "data" not in resp[0]:
        return pd.DataFrame(resp)

    rows: list[dict] = []
    for entry in resp:
        # v3 actual: {"contract": {...}, "data": [{...}, ...]}
        # legacy:    {"contract": {...}, "ticks": [[..], ...]}
        if isinstance(entry, dict) and ("ticks" in entry or "data" in entry):
            contract = entry.get("contract", {}) or {}
            items = entry.get("data") or entry.get("ticks") or []
            for t in items:
                if isinstance(t, list):
                    row = dict(zip(fmt, t)) if fmt else {}
                elif isinstance(t, dict):
                    row = dict(t)
                else:
                    continue
                # Promote contract fields onto the row (don't overwrite an
                # existing key from the data record).
                for f in contract:
                    row.setdefault(f, contract[f])
                rows.append(row)
        elif isinstance(entry, list):
            if fmt:
                rows.append(dict(zip(fmt, entry)))
        elif isinstance(entry, dict):
            rows.append(entry)
    return pd.DataFrame(rows)


def _extract_daily_spot(eod_df: pd.DataFrame,
                         days: pd.DatetimeIndex) -> dict[pd.Timestamp, float]:
    """Build a date -> close-price map from a v3 stock/history/eod frame.

    v3 returns ISO datetimes in ``created`` / ``last_trade`` (no plain ``date``
    column). We try those first and fall back to a YYYYMMDD ``date`` field if
    present (legacy / migration safety).
    """
    if eod_df.empty:
        return {}
    d = None
    for col in ("last_trade", "created"):
        if col in eod_df.columns:
            d = pd.to_datetime(eod_df[col], errors="coerce", utc=True).dt.tz_convert(None)
            break
    if d is None and "date" in eod_df.columns:
        d = pd.to_datetime(eod_df["date"].astype(str), format="%Y%m%d",
                            errors="coerce")
    if d is None:
        return {}
    close_col = next((c for c in ("close", "Close", "last", "price")
                      if c in eod_df.columns), None)
    if close_col is None:
        return {}
    s = pd.Series(eod_df[close_col].astype(float).values, index=d.values)
    s = s[s.index.notna()]
    s.index = pd.DatetimeIndex(s.index).normalize()
    return {ts: float(v) for ts, v in s.items() if ts in set(days.normalize())}


def _spot_from_local_cache(underlying: str, start: pd.Timestamp,
                            end: pd.Timestamp) -> dict[pd.Timestamp, float]:
    """Per-date underlying spot from the existing local ETF cache / yfinance.

    Used because the ThetaData Options Standard subscription does NOT include
    /v3/stock/history/eod. We use the unadjusted ``close`` (the actual quoted
    price on that date) for options analysis. Returns {} on cache miss; the
    canonical schema then carries NaN ``underlying_price`` and the validator
    will warn rather than error.
    """
    from ..loaders import load_prices
    try:
        panel = load_prices(
            [underlying.upper()],
            start=pd.Timestamp(start).strftime("%Y-%m-%d"),
            end=pd.Timestamp(end).strftime("%Y-%m-%d"),
            source="cache",
            allow_synthetic=False,
            validate=False,
            use_cache=True,
        )
    except Exception:
        return {}
    df = panel.get(underlying.upper())
    if df is None or df.empty or "close" not in df.columns:
        return {}
    out: dict[pd.Timestamp, float] = {}
    for d, p in df["close"].items():
        ts = pd.Timestamp(d).normalize()
        if pd.notna(p):
            out[ts] = float(p)
    return out


register_loader("thetadata", ThetaDataLoader)
