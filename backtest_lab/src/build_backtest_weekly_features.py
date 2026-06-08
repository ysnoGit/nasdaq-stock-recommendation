from __future__ import annotations

import pandas as pd

from backtest_lab.src.config import BACKTEST_SOURCE_S3_LABEL
from backtest_lab.src.calendar_utils import official_week_end_trading_date, week_start_for_date


def build_backtest_weekly_features(daily: pd.DataFrame) -> pd.DataFrame:
    required = [
        "snapshot_date",
        "gvkey",
        "iid",
        "adjusted_close_price",
        "volume",
    ]
    missing = [column for column in required if column not in daily.columns]
    if missing:
        raise RuntimeError(f"Daily feature frame missing weekly build columns: {missing}")

    work = daily.copy()
    work["snapshot_date"] = pd.to_datetime(work["snapshot_date"]).dt.date
    work["week_start_date"] = work["snapshot_date"].map(week_start_for_date)
    work["official_week_end_date"] = work["week_start_date"].map(official_week_end_trading_date)
    work = work[work["official_week_end_date"].notna()].copy()

    work = work.sort_values(["gvkey", "iid", "snapshot_date"])
    grouped = work.groupby(["gvkey", "iid", "week_start_date", "official_week_end_date"], dropna=False)
    weekly = grouped.agg(
        week_end_date=("snapshot_date", "max"),
        weekly_open_price=("adjusted_close_price", "first"),
        weekly_high_price=("adjusted_close_price", "max"),
        weekly_low_price=("adjusted_close_price", "min"),
        weekly_close_price=("adjusted_close_price", "last"),
        weekly_volume=("volume", "sum"),
        trading_days=("snapshot_date", "count"),
    ).reset_index()

    weekly = weekly[weekly["week_end_date"] == weekly["official_week_end_date"]].copy()
    weekly = weekly.rename(columns={"official_week_end_date": "calendar_week_end_date"})
    weekly = weekly.drop(columns=["calendar_week_end_date", "trading_days"])
    weekly = weekly.sort_values(["gvkey", "iid", "week_end_date"])

    for window in (5, 10, 30):
        weekly[f"weekly_ma{window}"] = (
            weekly.groupby(["gvkey", "iid"], dropna=False)["weekly_close_price"]
            .transform(lambda series: series.shift(1).rolling(window=window, min_periods=window).mean())
        )

    security_group = weekly.groupby(["gvkey", "iid"], dropna=False)
    weekly["weekly_h_confirmed_using_date"] = security_group["week_end_date"].shift(-1)
    weekly["future_weekly_ma5"] = security_group["weekly_ma5"].shift(-1)
    weekly["future_weekly_ma10"] = security_group["weekly_ma10"].shift(-1)
    weekly["future_weekly_ma30"] = security_group["weekly_ma30"].shift(-1)
    weekly["future_weekly_close_price"] = security_group["weekly_close_price"].shift(-1)
    weekly["source_s3_path"] = BACKTEST_SOURCE_S3_LABEL

    for column in ["week_start_date", "week_end_date", "weekly_h_confirmed_using_date"]:
        weekly[column] = pd.to_datetime(weekly[column]).dt.date

    duplicates = weekly.duplicated(["week_end_date", "gvkey", "iid"]).sum()
    if duplicates:
        raise RuntimeError(f"Backtest weekly features contain duplicate keys: {duplicates:,}")

    calendar_duplicates = weekly[["week_start_date", "week_end_date"]].drop_duplicates()
    bad_calendar = (
        calendar_duplicates.groupby("week_start_date")["week_end_date"].nunique() > 1
    )
    if bad_calendar.any():
        raise RuntimeError("Multiple weekly partitions found for at least one week_start_date.")

    print(f"Backtest weekly rows: {len(weekly):,}")
    print(
        "Backtest weekly week_end range: "
        f"{weekly['week_end_date'].min()} to {weekly['week_end_date'].max()}"
    )
    return weekly[
        [
            "week_start_date",
            "week_end_date",
            "gvkey",
            "iid",
            "weekly_open_price",
            "weekly_high_price",
            "weekly_low_price",
            "weekly_close_price",
            "weekly_volume",
            "weekly_ma5",
            "weekly_ma10",
            "weekly_ma30",
            "weekly_h_confirmed_using_date",
            "future_weekly_ma5",
            "future_weekly_ma10",
            "future_weekly_ma30",
            "future_weekly_close_price",
            "source_s3_path",
        ]
    ].copy()
