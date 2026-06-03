"""Catalyst CSV I/O (V6.1, read-only data layer).

Loads / saves ``Catalyst`` records from a CSV at a configurable path. No
network, no auto-fetch, no broker — the CSV is the source of truth in V6.1
and the per-sector drivers (V6.2+) are responsible for refreshing it.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .schema import CATALYST_FIELDS, Catalyst, SchemaError


def load_catalysts(path: str | Path) -> list[Catalyst]:
    """Return all valid ``Catalyst`` rows from ``path`` (empty list if file missing)."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[Catalyst] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs = {k: r.get(k, "") for k in CATALYST_FIELDS}
            # tier comes back as str from CSV; coerce.
            raw_tier = kwargs.get("tier", "")
            try:
                kwargs["tier"] = int(raw_tier) if str(raw_tier) != "" else 0
            except (TypeError, ValueError) as exc:
                raise SchemaError(
                    f"tier must be int, got {raw_tier!r}"
                ) from exc
            out.append(Catalyst(**kwargs))  # __post_init__ validates
    return out


def save_catalysts(catalysts: list[Catalyst], path: str | Path) -> Path:
    """Write ``catalysts`` to ``path`` in canonical CSV order."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CATALYST_FIELDS))
        writer.writeheader()
        for c in catalysts:
            writer.writerow(c.to_dict())
    return p


__all__ = ["load_catalysts", "save_catalysts"]
