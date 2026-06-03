"""Manual events CSV loader.

Reads ``data/events/manual_events.csv`` (or a caller-supplied path) and
exposes the events as either a long-format ``DataFrame`` or a
date-indexed boolean-flag panel suitable for joining onto trades.

Failure mode: returns an empty DataFrame if the file is missing. NEVER
raises on missing file; NEVER fetches anything from the network.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ..config import project_root


log = logging.getLogger("quantbot.events.manual")


def default_events_path(root: str | Path | None = None) -> Path:
    base = Path(root) if root else project_root()
    return base / "data" / "events" / "manual_events.csv"


def load_events(path: str | Path | None = None) -> pd.DataFrame:
    """Long-format DataFrame with columns ``date``, ``event_type``, ``note``.

    Returns an empty (but typed) DataFrame if the file does not exist.
    """
    p = Path(path) if path else default_events_path()
    if not p.is_file():
        log.info("manual events file not present at %s; continuing without events", p)
        return pd.DataFrame(columns=["date", "event_type", "note"])
    df = pd.read_csv(p)
    if "date" not in df.columns or "event_type" not in df.columns:
        log.warning("manual events file %s missing required columns "
                     "('date', 'event_type'); ignoring", p)
        return pd.DataFrame(columns=["date", "event_type", "note"])
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    if "note" not in df.columns:
        df["note"] = ""
    df["event_type"] = df["event_type"].astype(str).str.upper()
    return df[["date", "event_type", "note"]].dropna(subset=["date"]).sort_values("date")


def load_events_detailed(path: str | Path | None = None) -> pd.DataFrame:
    """Like :func:`load_events` but PRESERVES the richer optional columns
    (``event_name``, ``source``, ``importance``) when present in the CSV.

    Always returns the columns
    ``date, event_type, event_name, source, importance, note`` -- any
    column missing from the CSV is filled with an empty string (or
    "unknown" for importance). Returns an empty (typed) frame if the file
    does not exist. NEVER raises on missing file; NEVER hits the network.

    This is additive: :func:`load_events` is unchanged so existing callers
    and tests keep their exact 3-column contract.
    """
    cols = ["date", "event_type", "event_name", "source", "importance", "note"]
    p = Path(path) if path else default_events_path()
    if not p.is_file():
        log.info("manual events file not present at %s; continuing without events", p)
        return pd.DataFrame(columns=cols)
    df = pd.read_csv(p)
    if "date" not in df.columns or "event_type" not in df.columns:
        log.warning("manual events file %s missing required columns "
                     "('date', 'event_type'); ignoring", p)
        return pd.DataFrame(columns=cols)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["event_type"] = df["event_type"].astype(str).str.upper()
    # Accept either 'note' or 'notes' as the free-text column.
    if "note" not in df.columns and "notes" in df.columns:
        df = df.rename(columns={"notes": "note"})
    for c, default in (("event_name", ""), ("source", ""),
                        ("importance", "unknown"), ("note", "")):
        if c not in df.columns:
            df[c] = default
    df["importance"] = df["importance"].astype(str).str.lower()
    return df[cols].dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def build_event_flag_panel(
    events: pd.DataFrame, *,
    date_index: pd.DatetimeIndex,
    event_types: list[str] | None = None,
) -> pd.DataFrame:
    """Date-indexed boolean panel: one column per ``event_type``.

    ``True`` at row ``d`` iff at least one event of that type occurred on
    ``d``. Rows outside ``events['date']`` are ``False``.
    """
    types = (event_types
              or sorted(events["event_type"].unique().tolist())
              if not events.empty else [])
    panel = pd.DataFrame(False, index=date_index, columns=types)
    if events.empty or not types:
        return panel
    for et in types:
        dates = events.loc[events["event_type"] == et, "date"].unique()
        panel.loc[panel.index.isin(dates), et] = True
    return panel
