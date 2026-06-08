from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

import pandas as pd


@lru_cache(maxsize=1)
def get_us_equity_calendar():
    try:
        import exchange_calendars as xcals
    except ImportError as exc:
        raise RuntimeError(
            "exchange_calendars is required for official U.S. market week-end logic. "
            "Install project requirements before building weekly metrics."
        ) from exc

    calendar_names = set(xcals.get_calendar_names())
    calendar_name = "XNAS" if "XNAS" in calendar_names else "XNYS"
    # XNAS is preferred. Some exchange_calendars releases alias XNAS to the
    # equivalent U.S. equities holiday calendar used by XNYS.
    return xcals.get_calendar(calendar_name)


def week_start_for_date(value: date | str | pd.Timestamp) -> date:
    value_date = pd.Timestamp(value).date()
    return value_date - timedelta(days=value_date.weekday())


def official_week_end_trading_dates(
    start_date: date | str | pd.Timestamp,
    end_date: date | str | pd.Timestamp,
) -> dict[date, date]:
    start = week_start_for_date(start_date)
    end = week_start_for_date(end_date) + timedelta(days=6)
    sessions = get_us_equity_calendar().sessions_in_range(
        pd.Timestamp(start),
        pd.Timestamp(end),
    )

    week_end_by_start: dict[date, date] = {}
    for session in sessions:
        session_date = pd.Timestamp(session).date()
        week_start = week_start_for_date(session_date)
        week_end_by_start[week_start] = session_date

    return week_end_by_start


def official_week_end_trading_date(week_start_date: date | str | pd.Timestamp) -> date | None:
    week_start = week_start_for_date(week_start_date)
    return official_week_end_trading_dates(week_start, week_start).get(week_start)


def is_official_week_end_trading_date(value: date | str | pd.Timestamp) -> bool:
    value_date = pd.Timestamp(value).date()
    return official_week_end_trading_date(value_date) == value_date
