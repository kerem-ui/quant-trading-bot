"""Shared pytest fixtures."""

import csv
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

# Ensure src/ on path even if pytest is invoked oddly.
SRC = Path(__file__).resolve().parents[1] / "src"
REPO_ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quantbot.data.loaders import generate_synthetic_panel  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def reproducible_checkout_data():
    """Materialize small deterministic fixtures expected by legacy smoke tests.

    The repository intentionally ignores ``/data`` because real market and SEC
    caches are local. Some older integration tests nevertheless described their
    inputs as committed data. Copy the curated research fixtures and create a
    synthetic SPY series only when those local paths are absent. Pre-existing
    user data is never overwritten, and files created here are removed after
    the session.
    """
    fixture_dir = (
        REPO_ROOT / "tests" / "fixtures" / "reproducibility"
        / "sector_tracker"
    )
    sector_dir = REPO_ROOT / "data" / "research" / "sector_tracker"
    created: list[Path] = []

    for source in sorted(fixture_dir.glob("*.csv")):
        target = sector_dir / source.name
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            created.append(target)

    spy_path = REPO_ROOT / "data" / "cache" / "SPY.csv"
    if not spy_path.exists():
        spy_path.parent.mkdir(parents=True, exist_ok=True)
        day = date(2025, 1, 2)
        rows: list[tuple[str, float]] = []
        while len(rows) < 300:
            if day.weekday() < 5:
                i = len(rows)
                close = 100.0 + i * 0.1 + ((i % 10) - 5) * 0.05
                rows.append((day.isoformat(), close))
            day += timedelta(days=1)
        with spy_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(("date", "close"))
            writer.writerows(rows)
        created.append(spy_path)

    yield

    for path in reversed(created):
        path.unlink(missing_ok=True)
    for directory in (
        REPO_ROOT / "data" / "cache",
        sector_dir,
        sector_dir.parent,
        REPO_ROOT / "data" / "research",
        REPO_ROOT / "data",
    ):
        if directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()


@pytest.fixture(scope="session")
def sector_map():
    return {
        "SPY": "broad", "IVV": "broad", "VOO": "broad",
        "QQQ": "tech", "XLK": "tech",
        "GLD": "metals", "IAU": "metals",
        "XLF": "fin", "KBE": "fin", "TLT": "rates",
    }


@pytest.fixture(scope="session")
def panel(sector_map):
    return generate_synthetic_panel(
        list(sector_map), "2013-01-01", "2021-01-01", seed=7, sector_map=sector_map
    )


@pytest.fixture(scope="session")
def small_panel(sector_map):
    syms = {k: sector_map[k] for k in ["SPY", "QQQ", "GLD", "TLT"]}
    return generate_synthetic_panel(
        list(syms), "2015-01-01", "2020-01-01", seed=3, sector_map=syms
    )
