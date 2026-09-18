"""Versioned daily US cash-equity calendar, scoped to 2010--2026.

Session labels are naive local dates; session times are America/New_York.
No provider calls, intraday bars or additional dependencies are involved.
"""
from dataclasses import dataclass
from functools import lru_cache

import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, Holiday, GoodFriday,
    USMartinLutherKingJr, USPresidentsDay, USMemorialDay, USLaborDay, USThanksgivingDay,
    nearest_workday, sunday_to_monday)


class _Holidays(AbstractHolidayCalendar):
    rules = [Holiday('New Year', month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday('Juneteenth', month=6, day=19, start_date='2022-01-01', observance=nearest_workday),
        Holiday('Independence', month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday('Christmas', month=12, day=25, observance=nearest_workday)]


@lru_cache(maxsize=17)
def _year_sessions(year: int) -> pd.DatetimeIndex:
    days = pd.bdate_range(f'{year}-01-01', f'{year}-12-31')
    closed = _Holidays().holidays(days[0], days[-1])
    exceptional = pd.to_datetime(['2012-10-29','2012-10-30','2018-12-05','2025-01-09'])
    return days.difference(closed.union(exceptional))


@dataclass(frozen=True)
class MarketSession:
    """One US equity session: label and timezone-aware open/close."""
    date: pd.Timestamp
    open: pd.Timestamp
    close: pd.Timestamp


@lru_cache(maxsize=17)
def _early_closes(year: int) -> frozenset:
    thanksgiving = USThanksgivingDay.dates(f'{year}-01-01',f'{year}-12-31')[0]
    return frozenset([thanksgiving+pd.Timedelta(days=1),
                      pd.Timestamp(year,7,3),pd.Timestamp(year,12,24)])


class USMarketCalendar:
    """NYSE/US ETF regular sessions; reject dates outside the reviewed scope."""
    name = 'US-equity-2010-2026-v1'

    def label(self, value) -> pd.Timestamp:
        """Require an unambiguous daily local session label, not a timestamp."""
        day = pd.Timestamp(value)
        if pd.isna(day) or day.tzinfo is not None or day != day.normalize():
            raise ValueError(f'Expected naive daily session label: {value}')
        if not 2010 <= day.year <= 2026:
            raise ValueError('Calendar supported years are 2010 through 2026')
        return day

    def is_session(self, value) -> bool:
        """Whether a local date is a regular trading session."""
        day = self.label(value)
        return day in _year_sessions(day.year)

    def sessions(self, start, end) -> pd.DatetimeIndex:
        """Return inclusive daily session labels, excluding exchange closures."""
        start, end = self.label(start), self.label(end)
        if end < start:
            raise ValueError('Session range is reversed')
        days = _year_sessions(start.year)
        for year in range(start.year+1, end.year+1):
            days = days.append(_year_sessions(year))
        return days[(days >= start) & (days <= end)].copy()

    def next_session(self, value) -> pd.Timestamp:
        """First exchange session strictly after a signal's local date."""
        day = self.label(value)
        candidate = day + pd.Timedelta(days=1)
        while not self.is_session(candidate):
            candidate += pd.Timedelta(days=1)
        return candidate

    def session(self, value) -> MarketSession:
        """Regular 09:30 open and 16:00/13:00 close in New York time."""
        day = self.label(value)
        if not self.is_session(day):
            raise ValueError(f'non-session date: {day.date()}')
        early = day in _early_closes(day.year)
        start = (day+pd.Timedelta(hours=9,minutes=30)).tz_localize('America/New_York')
        end = (day+pd.Timedelta(hours=13 if early else 16)).tz_localize('America/New_York')
        return MarketSession(day, start, end)

    def validate_index(self, index: pd.DatetimeIndex) -> None:
        """Reject duplicate, ambiguous, closed or missing global session labels."""
        if not isinstance(index,pd.DatetimeIndex) or index.empty:
            raise ValueError('Expected nonempty DatetimeIndex')
        if index.has_duplicates or not index.is_monotonic_increasing:
            raise ValueError('Session index must be unique and increasing')
        for day in index:
            if not self.is_session(day):
                raise ValueError(f'non-session price bar: {day.date()}')
        missing = self.sessions(index[0],index[-1]).difference(index)
        if len(missing):
            raise ValueError(f'missing market session: {missing[0].date()}')
