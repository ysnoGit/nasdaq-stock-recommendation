from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtest_lab.src.config import (  # noqa: E402
    BACKTEST_SOURCE_S3_LABEL,
    BACKTEST_WARMUP_CALENDAR_DAYS,
)
from server_pipeline.daily.build_daily_market_metrics_s3 import (  # noqa: E402
    list_raw_objects,
    parse_raw_files,
)
from server_pipeline.s3_duckdb import connect_duckdb_with_s3  # noqa: E402
from server_pipeline.utils.universe_filter import add_universe_filter_columns  # noqa: E402


def select_raw_paths(start_date, end_date, warmup_calendar_days: int) -> list[str]:
    keys = list_raw_objects()
    yearly_files, date_partition_files = parse_raw_files(keys)

    warmup_start = start_date - timedelta(days=warmup_calendar_days)
    paths = []

    for item in yearly_files:
        year_start = pd.Timestamp(item["year"], 1, 1).date()
        year_end = pd.Timestamp(item["year"], 12, 31).date()
        if year_end >= warmup_start and year_start <= end_date:
            paths.append(item["path"])

    for item in date_partition_files:
        if warmup_start <= item["date"] <= end_date:
            paths.append(item["path"])

    paths = sorted(set(paths))
    if not paths:
        raise RuntimeError(
            "No raw daily S3 files selected for backtest. "
            f"Checked source prefix: {BACKTEST_SOURCE_S3_LABEL}"
        )
    return paths


def build_backtest_daily_features(
    start_date,
    end_date=None,
    warmup_calendar_days: int = BACKTEST_WARMUP_CALENDAR_DAYS,
) -> pd.DataFrame:
    start_date = pd.Timestamp(start_date).date()
    if end_date is None:
        end_date = pd.Timestamp.utcnow().date()
    else:
        end_date = pd.Timestamp(end_date).date()

    raw_paths = select_raw_paths(start_date, end_date, warmup_calendar_days)
    warmup_start = start_date - timedelta(days=warmup_calendar_days)

    print("Building backtest daily features from existing S3 raw daily files.")
    print(f"Source prefix: {BACKTEST_SOURCE_S3_LABEL}")
    print(f"Backtest date window: {start_date} to {end_date}")
    print(f"Warm-up start date: {warmup_start}")
    print(f"Raw files selected: {len(raw_paths):,}")

    con = connect_duckdb_with_s3()
    query = f"""
    WITH raw_input AS (
        SELECT *
        FROM read_parquet({raw_paths}, union_by_name = true)
    ),
    raw_clean AS (
        SELECT
            CAST(date AS DATE) AS snapshot_date,
            CAST(gvkey AS VARCHAR) AS gvkey,
            CAST(iid AS VARCHAR) AS iid,
            ticker,
            company_name,
            exchange_code,
            security_status,
            issue_type_code,
            close_price_raw,
            open_price_raw,
            high_price_raw,
            low_price_raw,
            volume,
            CASE
                WHEN adjusted_close_price IS NOT NULL THEN adjusted_close_price
                WHEN adjustment_factor IS NOT NULL
                 AND adjustment_factor != 0
                 AND close_price_raw IS NOT NULL
                THEN close_price_raw / adjustment_factor
                ELSE close_price_raw
            END AS adjusted_close_price
        FROM raw_input
        WHERE CAST(date AS DATE) BETWEEN DATE '{warmup_start}' AND DATE '{end_date}'
    ),
    base AS (
        SELECT *
        FROM raw_clean
        WHERE adjusted_close_price IS NOT NULL
          AND volume IS NOT NULL
    ),
    dedup AS (
        SELECT *
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY snapshot_date, gvkey, iid
                    ORDER BY snapshot_date DESC
                ) AS rn
            FROM base
        )
        WHERE rn = 1
    ),
    indicators AS (
        SELECT
            *,
            AVG(adjusted_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY snapshot_date
                ROWS BETWEEN 19 PRECEDING AND CURRENT ROW
            ) AS ma20,
            AVG(adjusted_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY snapshot_date
                ROWS BETWEEN 49 PRECEDING AND CURRENT ROW
            ) AS ma50,
            AVG(adjusted_close_price) OVER (
                PARTITION BY gvkey, iid
                ORDER BY snapshot_date
                ROWS BETWEEN 99 PRECEDING AND CURRENT ROW
            ) AS ma100,
            AVG(volume) OVER (
                PARTITION BY gvkey, iid
                ORDER BY snapshot_date
                ROWS BETWEEN 30 PRECEDING AND 1 PRECEDING
            ) AS volume_ma30
        FROM dedup
    ),
    with_future AS (
        SELECT
            *,
            volume / NULLIF(volume_ma30, 0) AS volume_ratio,
            snapshot_date - INTERVAL 45 DAYS AS volume_lookback_start_date,
            snapshot_date - INTERVAL 1 DAY AS volume_lookback_end_date,
            LEAD(snapshot_date) OVER (
                PARTITION BY gvkey, iid ORDER BY snapshot_date
            ) AS daily_f_confirmed_using_date,
            LEAD(ma20) OVER (
                PARTITION BY gvkey, iid ORDER BY snapshot_date
            ) AS future_daily_ma20,
            LEAD(ma50) OVER (
                PARTITION BY gvkey, iid ORDER BY snapshot_date
            ) AS future_daily_ma50,
            LEAD(ma100) OVER (
                PARTITION BY gvkey, iid ORDER BY snapshot_date
            ) AS future_daily_ma100,
            LEAD(close_price_raw) OVER (
                PARTITION BY gvkey, iid ORDER BY snapshot_date
            ) AS future_daily_close_price,
            LEAD(adjusted_close_price) OVER (
                PARTITION BY gvkey, iid ORDER BY snapshot_date
            ) AS future_daily_adjusted_close_price
        FROM indicators
    )
    SELECT
        snapshot_date,
        gvkey,
        iid,
        ticker,
        company_name,
        exchange_code,
        security_status,
        issue_type_code,
        close_price_raw AS close_price,
        adjusted_close_price,
        volume,
        volume_ma30,
        volume_ratio,
        CAST(volume_lookback_start_date AS DATE) AS volume_lookback_start_date,
        CAST(volume_lookback_end_date AS DATE) AS volume_lookback_end_date,
        ma20,
        ma50,
        ma100,
        daily_f_confirmed_using_date,
        future_daily_ma20,
        future_daily_ma50,
        future_daily_ma100,
        future_daily_close_price,
        future_daily_adjusted_close_price,
        '{BACKTEST_SOURCE_S3_LABEL}' AS source_s3_path
    FROM with_future
    WHERE snapshot_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
    ORDER BY snapshot_date, gvkey, iid
    """
    df = con.execute(query).fetchdf()

    if df.empty:
        raise RuntimeError("Backtest daily feature build produced zero rows.")

    for column in [
        "snapshot_date",
        "volume_lookback_start_date",
        "volume_lookback_end_date",
        "daily_f_confirmed_using_date",
    ]:
        df[column] = pd.to_datetime(df[column]).dt.date

    duplicates = df.duplicated(["snapshot_date", "gvkey", "iid"]).sum()
    if duplicates:
        raise RuntimeError(f"Backtest daily features contain duplicate keys: {duplicates:,}")

    print(f"Backtest daily rows: {len(df):,}")
    print(f"Backtest daily date range: {df['snapshot_date'].min()} to {df['snapshot_date'].max()}")
    return df


def build_backtest_security_master(daily: pd.DataFrame) -> pd.DataFrame:
    latest_date = daily["snapshot_date"].max()
    grouped = daily.groupby(["gvkey", "iid"], dropna=False)
    first_seen = grouped["snapshot_date"].min().rename("first_seen_date")
    last_seen = grouped["snapshot_date"].max().rename("last_seen_date")
    latest_identity = (
        daily.sort_values(["gvkey", "iid", "snapshot_date"])
        .groupby(["gvkey", "iid"], as_index=False, dropna=False)
        .tail(1)
        .set_index(["gvkey", "iid"])
    )
    master = latest_identity.join(first_seen).join(last_seen).reset_index()
    master = master.rename(columns={"issue_type_code": "security_type"})
    master["is_active"] = master["last_seen_date"] == latest_date
    master = add_universe_filter_columns(master)

    out = master[
        [
            "gvkey",
            "iid",
            "ticker",
            "company_name",
            "exchange_code",
            "security_status",
            "security_type",
            "is_active",
            "is_excluded_universe",
            "exclusion_reason",
            "first_seen_date",
            "last_seen_date",
            "source_s3_path",
        ]
    ].copy()
    duplicates = out.duplicated(["gvkey", "iid"]).sum()
    if duplicates:
        raise RuntimeError(f"Backtest security master contains duplicate keys: {duplicates:,}")
    print(f"Backtest security master rows: {len(out):,}")
    return out
