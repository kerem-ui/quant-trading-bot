"""Explicit daily cash and supplied corporate-action conventions.

Dividends use prior-close entitlement and ex-date cash recognition (not a
broker payment-date/receivable ledger). No events or rates are inferred.
"""
from dataclasses import dataclass
from math import isfinite

import pandas as pd


@dataclass(frozen=True)
class CorporateAction:
    """Split ratio or USD dividend per pre-event share, before ex-date trading."""
    symbol: str
    date: object
    kind: str
    value: float
    convention: str = 'prior_close_ex_date_cash'


@dataclass(frozen=True)
class CorporateActionBook:
    """Caller-attested complete action coverage; an empty book is not inferred."""
    events: tuple[CorporateAction, ...]
    symbols: tuple[str, ...]
    start: object
    end: object
    source: str
    complete: bool

    def validate(self, panel, dates, calendar) -> None:
        """Reject incomplete/ambiguous history, identity, timing or price basis."""
        if self.complete is not True or not self.source.strip():
            raise ValueError('A complete corporate-action book with source is required')
        if (set(self.symbols) != set(panel) or len(set(self.symbols)) != len(self.symbols)
                or calendar.label(self.start) > dates[0] or calendar.label(self.end) < dates[-1]):
            raise ValueError('Incomplete corporate-action symbol/date coverage')
        for symbol, df in panel.items():
            if df.attrs.get('price_basis') != 'raw_unadjusted':
                raise ValueError(f'{symbol}: raw_unadjusted price attestation required')
        seen = set()
        for action in self.events:
            day = calendar.label(action.date)
            if (action.symbol not in panel or not calendar.is_session(day)
                    or day < calendar.label(self.start) or day > calendar.label(self.end)
                    or action.kind not in ('split','dividend','special_dividend')
                    or not isfinite(action.value) or action.value <= 0
                    or action.convention != 'prior_close_ex_date_cash'):
                raise ValueError(f'Unsupported/ambiguous corporate action: {action.symbol} {day.date()}')
            key = (action.symbol, day)
            if key in seen:
                raise ValueError(f'Ambiguous multiple corporate actions: {key}')
            seen.add(key)

    def on(self, date) -> tuple[CorporateAction, ...]:
        """Return supplied events effective before trading on this session."""
        return tuple(a for a in self.events if pd.Timestamp(a.date) == date)

    def metadata(self) -> dict:
        """Record the exact supplied action assumptions in the backtest result."""
        return dict(source=self.source,complete=self.complete,symbols=list(self.symbols),
            start=str(pd.Timestamp(self.start).date()),end=str(pd.Timestamp(self.end).date()),
            events=[dict(symbol=a.symbol,date=str(pd.Timestamp(a.date).date()),
                         kind=a.kind,value=a.value,convention=a.convention) for a in self.events])


@dataclass(frozen=True)
class CashBalanceModel:
    """ACT/365F on previous closing balances; rates are supplied annual decimals.

Eligible credit = max(cash - marked short collateral, 0). Debit = max(-cash,0).
None financing means borrowing is prohibited, including transaction-fee debt.
"""
    interest_rate: float = 0.0
    financing_rate: float | None = None

    def __post_init__(self):
        if self.interest_rate is None:
            raise ValueError('cash interest rate must be supplied (zero disables it)')
        for value in (self.interest_rate,self.financing_rate):
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError('Cash/financing rates must be finite nonnegative annual decimals')

    def validate_cash(self, cash: float) -> None:
        """Prevent an unconfigured debit balance (allow only roundoff dust)."""
        if not isfinite(cash):
            raise ValueError('Non-finite cash balance')
        if cash < -1e-9 and self.financing_rate is None:
            raise ValueError('Negative cash requires an explicit financing_rate; no implicit free leverage')

    def accrual(self, cash: float, short_collateral: float, days: int) -> tuple[float,float]:
        """Return positive credit interest and positive debit financing charge."""
        self.validate_cash(cash)
        if not isfinite(short_collateral) or short_collateral < 0 or days < 0:
            raise ValueError('Invalid accrual balance/interval')
        return (max(cash-short_collateral,0)*self.interest_rate*days/365,
                max(-cash,0)*(self.financing_rate or 0)*days/365)
