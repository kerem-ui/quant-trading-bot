"""Emergency-exit CSV I/O (V6.1, read-only data layer).

A separate file from catalysts. A ``TRIGGERED`` exit forces the sector signal
to ``EXIT_WATCH`` regardless of the catalyst score; this is still a research
recommendation, NOT a broker order.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .schema import EXIT_FIELDS, EmergencyExit


def load_exits(path: str | Path) -> list[EmergencyExit]:
    """Return all valid ``EmergencyExit`` rows from ``path`` (empty list if missing)."""
    p = Path(path)
    if not p.is_file():
        return []
    out: list[EmergencyExit] = []
    with p.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            kwargs = {k: r.get(k, "") for k in EXIT_FIELDS}
            out.append(EmergencyExit(**kwargs))  # __post_init__ validates
    return out


def save_exits(exits: list[EmergencyExit], path: str | Path) -> Path:
    """Write ``exits`` to ``path`` in canonical CSV order."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(EXIT_FIELDS))
        writer.writeheader()
        for e in exits:
            writer.writerow(e.to_dict())
    return p


__all__ = ["load_exits", "save_exits"]
