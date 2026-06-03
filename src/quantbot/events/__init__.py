"""V5.7 events layer (manual CSV input only).

This package is a deliberate **stub**. It exposes a single loader that
reads a manually-curated event CSV (``data/events/manual_events.csv`` by
default) so other research code can flag trades that overlapped CPI / FOMC /
earnings windows. There is NO live news provider, NO IBKR news, NO external
API call. Future V6+ work may add provider-backed loaders here; until then
the schema and folder layout are reserved.

Schema for ``manual_events.csv``::

    date,event_type,note
    2022-01-12,CPI,"Dec 2021 CPI release"
    2022-01-26,FOMC,"FOMC statement"
    ...

``event_type`` is a free-text label; common values used by the V5.7 driver
are ``CPI``, ``FOMC``, ``EARNINGS``, ``MACRO``.
"""

from __future__ import annotations
