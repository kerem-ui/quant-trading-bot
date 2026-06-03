"""Shared pytest fixtures."""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Ensure src/ on path even if pytest is invoked oddly.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quantbot.data.loaders import generate_synthetic_panel  # noqa: E402


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
