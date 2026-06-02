import argparse
from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
from pathlib import Path
import re
import sys

import boto3
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from server_pipeline.config import (
    S3_BUCKET,
    DAILY_MARKET_METRICS_PREFIX,
    WEEKLY_MARKET_METRICS_PREFIX,
    ANNUAL_GROWTH_HISTORY_PREFIX,
    QUARTERLY_GROWTH_HISTORY_PREFIX,
    SCREENING_RESULTS_PREFIX,
)
from server_pipeline.s3_duckdb import connect_duckdb_with_s3
from server_pipeline.utils.universe_filter import (
    add_universe_filter_columns,
    universe_exclusion_reasons,
)

FLAG_COLUMNS = [
    "flag_a",
    "flag_b",
    "flag_ab",
    "flag_c",
    "flag_d",
    "flag_cd",
    "flag_e",
    "flag_f",
    "flag_g",
    "flag_h",
    "flag_all",
]


def list_partitioned_parquet_paths(prefix: str, pattern: re.Pattern[str]) -> list[str]:
    s3 = boto3.client("s3")
    paginator = s3.get_paginator("list_objects_v2")

    paths = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=f"{prefix}/"):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if pattern.match(key):
                paths.append(f"s3://{S3_BUCKET}/{key}")

    if not paths:
        raise RuntimeError(
            f"No partitioned parquet files found under s3://{S3_BUCKET}/{prefix}/"
        )

    return sorted(paths)


def list_daily_metric_paths() -> list[str]:
    pattern = re.compile(
        rf"{DAILY_MARKET_METRICS_PREFIX}/year=\d{{4}}/month=\d{{2}}/"
        r"date=\d{4}-\d{2}-\d{2}/daily_market_metrics_\d{4}-\d{2}-\d{2}\.parquet$"
    )
    return list_partitioned_parquet_paths(DAILY_MARKET_METRICS_PREFIX, pattern)


def list_weekly_metric_paths() -> list[str]:
    pattern = re.compile(
        rf"{WEEKLY_MARKET_METRICS_PREFIX}/year=\d{{4}}/"
        r"week_start_date=\d{4}-\d{2}-\d{2}/weekly_market_metrics_\d{4}-\d{2}-\d{2}\.parquet$"
    )
    return list_partitioned_parquet_paths(WEEKLY_MARKET_METRICS_PREFIX, pattern)


def upload_df_to_s3_parquet(df: pd.DataFrame, s3_key: str) -> None:
    buffer = BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    boto3.client("s3").put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=buffer.getvalue(),
    )


def upload_df_to_s3_csv(df: pd.DataFrame, s3_key: str) -> None:
    buffer = StringIO()
    df.to_csv(buffer, index=False)

    boto3.client("s3").put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=buffer.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )


def upload_json_to_s3(payload: dict, s3_key: str) -> None:
    boto3.client("s3").put_object(
        Bucket=S3_BUCKET,
        Key=s3_key,
        Body=json.dumps(payload, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )


def flag_counts(df: pd.DataFrame) -> dict[str, int]:
    return {
        column: int(df[column].fillna(False).sum())
        for column in FLAG_COLUMNS
        if column in df.columns
    }


def exclusion_reason_counts(excluded_df: pd.DataFrame) -> dict[str, int]:
    counts: dict[str, int] = {}
    if excluded_df.empty:
        return counts

    for value in excluded_df["exclusion_reason"].dropna():
        for reason in str(value).split("; "):
            if reason:
                counts[reason] = counts.get(reason, 0) + 1

    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def build_screening_summary(
    unfiltered_df: pd.DataFrame,
    filtered_df: pd.DataFrame,
    excluded_df: pd.DataFrame,
    universe_filter_enabled: bool,
) -> dict:
    return {
        "universe_filter_enabled": universe_filter_enabled,
        "total_rows_before_universe_filter": int(len(unfiltered_df)),
        "rows_excluded_by_universe_filter": int(len(excluded_df)),
        "rows_after_universe_filter": int(len(filtered_df)),
        "flag_counts_before_filtering": flag_counts(unfiltered_df),
        "flag_counts_after_filtering": flag_counts(filtered_df),
        "flag_all_count_before_filtering": int(unfiltered_df["flag_all"].fillna(False).sum()),
        "flag_all_count_after_filtering": int(filtered_df["flag_all"].fillna(False).sum()),
        "top_exclusion_reasons": exclusion_reason_counts(excluded_df),
    }


def validate_universe_filter_rules() -> None:
    samples = pd.DataFrame(
        [
            {"ticker": "BEAG", "iid": "01", "company_name": "BOLD EAGLE ACQUTN CORP -REDH"},
            {"ticker": "TESTW", "iid": "01", "company_name": "EXAMPLE WARRANTS"},
            {"ticker": "TSTR", "iid": "01", "company_name": "EXAMPLE RIGHTS"},
            {"ticker": "TSTU", "iid": "01", "company_name": "EXAMPLE UNITS"},
            {"ticker": "SPAC", "iid": "01", "company_name": "BLANK CHECK ACQUISITION CORP"},
            {"ticker": "NVDA", "iid": "01", "company_name": "NVIDIA CORP"},
            {"ticker": "AMZN", "iid": "01", "company_name": "AMAZON COM INC"},
            {"ticker": "META", "iid": "01", "company_name": "META PLATFORMS INC"},
            {"ticker": "ADBE", "iid": "01", "company_name": "ADOBE INC"},
            {"ticker": "ISRG", "iid": "01", "company_name": "INTUITIVE SURGICAL INC"},
            {"ticker": "MEDP", "iid": "01", "company_name": "MEDPACE HOLDINGS INC"},
        ]
    )
    annotated = add_universe_filter_columns(samples)

    should_exclude = ["BEAG", "TESTW", "TSTR", "TSTU", "SPAC"]
    should_keep = ["NVDA", "AMZN", "META", "ADBE", "ISRG", "MEDP"]

    bad_kept = annotated[
        annotated["ticker"].isin(should_exclude)
        & ~annotated["is_excluded_universe"]
    ]
    bad_excluded = annotated[
        annotated["ticker"].isin(should_keep)
        & annotated["is_excluded_universe"]
    ]

    if not bad_kept.empty or not bad_excluded.empty:
        raise RuntimeError(
            "Universe filter validation failed.\n"
            f"Expected exclusions kept:\n{bad_kept.to_string(index=False)}\n"
            f"Expected normal companies excluded:\n{bad_excluded.to_string(index=False)}"
        )

    print("Universe filter validation passed.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build final NASDAQ stock screening results directly from S3."
    )
    parser.add_argument(
        "--n-pct",
        type=float,
        default=10.0,
        help="Growth threshold percentage for A/B. Example: 10 means 10%%.",
    )
    parser.add_argument(
        "--annual-years",
        type=int,
        default=3,
        help="Number of recent annual YoY growth periods for A.",
    )
    parser.add_argument(
        "--quarter-count",
        type=int,
        default=4,
        help="Number of recent quarterly YoY growth periods for B.",
    )
    parser.add_argument(
        "--q",
        type=float,
        default=5.0,
        help="Volume surge multiple for C/D. Example: 5 means volume >= 5x MA30.",
    )
    parser.add_argument(
        "--m",
        type=int,
        default=3,
        help="Minimum number of volume surge days in recent 3 months for D.",
    )
    parser.add_argument(
        "--disable-universe-filter",
        action="store_true",
        help="Write the main screening output without excluding SPAC/redeemable/security-type rows.",
    )
    parser.add_argument(
        "--write-unfiltered-audit",
        action="store_true",
        help="Also write unfiltered screening result snapshots for comparison.",
    )
    parser.add_argument(
        "--validate-universe-filter",
        action="store_true",
        help="Run local universe-filter rule validation and exit.",
    )

    args = parser.parse_args()

    if args.validate_universe_filter:
        validate_universe_filter_rules()
        return

    n = args.n_pct / 100.0
    annual_years = args.annual_years
    quarter_count = args.quarter_count
    q = args.q
    m = args.m

    daily_paths = list_daily_metric_paths()
    weekly_paths = list_weekly_metric_paths()
    annual_growth_path = (
        f"s3://{S3_BUCKET}/{ANNUAL_GROWTH_HISTORY_PREFIX}/"
        "annual_fundamental_growth_history.parquet"
    )
    quarterly_growth_path = (
        f"s3://{S3_BUCKET}/{QUARTERLY_GROWTH_HISTORY_PREFIX}/"
        "quarterly_fundamental_growth_history.parquet"
    )

    created_at = datetime.now(timezone.utc).isoformat()

    print("=" * 80)
    print("Building final screening results from S3")
    print(f"Daily metric partitions: {len(daily_paths):,}")
    print(f"Weekly metric partitions: {len(weekly_paths):,}")
    print(f"Annual growth input: {annual_growth_path}")
    print(f"Quarterly growth input: {quarterly_growth_path}")
    print(f"n threshold: {args.n_pct:.2f}%")
    print(f"annual_years: {annual_years}")
    print(f"quarter_count: {quarter_count}")
    print(f"q volume multiple: {q}")
    print(f"m surge count: {m}")
    print(f"Universe quality filter enabled: {not args.disable_universe_filter}")
    print("=" * 80)

    con = connect_duckdb_with_s3()

    query = f"""
    WITH latest_daily_date AS (
        SELECT
            MAX(CAST(date AS DATE)) AS screening_date
        FROM read_parquet({daily_paths}, union_by_name = true)
    ),

    recent_daily AS (
        SELECT
            CAST(d.date AS DATE) AS date,
            d.gvkey,
            d.iid,
            d.ticker,
            d.company_name,
            d.currency,
            d.adjusted_close_price,
            d.close_price_raw,
            d.volume,
            d.volume_ma30,
            d.volume_ratio,
            d.ma20,
            d.ma50,
            d.ma100,
            d.flag_e,
            d.flag_f,
            ld.screening_date
        FROM read_parquet({daily_paths}, union_by_name = true) AS d
        CROSS JOIN latest_daily_date AS ld
        WHERE CAST(d.date AS DATE) >= ld.screening_date - INTERVAL '3 months'
          AND CAST(d.date AS DATE) <= ld.screening_date
    ),

    latest_daily AS (
        SELECT
            *
        FROM recent_daily
        WHERE date = screening_date
    ),

    volume_counts AS (
        SELECT
            gvkey,
            iid,
            COUNT(*) FILTER (
                WHERE volume_ratio >= {q}
            ) AS surge_day_count_3m
        FROM recent_daily
        GROUP BY gvkey, iid
    ),

    daily_result AS (
        SELECT
            d.screening_date,
            d.gvkey,
            d.iid,
            d.ticker,
            d.company_name,
            d.currency,
            d.adjusted_close_price,
            d.close_price_raw,
            d.volume,
            d.volume_ma30,
            d.volume_ratio,

            CASE
                WHEN d.volume_ratio >= {q}
                THEN TRUE ELSE FALSE
            END AS flag_c,

            COALESCE(v.surge_day_count_3m, 0) AS surge_day_count_3m,

            CASE
                WHEN COALESCE(v.surge_day_count_3m, 0) >= {m}
                THEN TRUE ELSE FALSE
            END AS flag_d,

            d.ma20,
            d.ma50,
            d.ma100,

            CASE
                WHEN d.ma20 IS NOT NULL
                 AND d.ma50 IS NOT NULL
                 AND d.ma100 IS NOT NULL
                THEN (
                    GREATEST(d.ma20, d.ma50, d.ma100)
                    - LEAST(d.ma20, d.ma50, d.ma100)
                ) / NULLIF((d.ma20 + d.ma50 + d.ma100) / 3, 0)
                ELSE NULL
            END AS daily_ma_cluster_ratio,

            d.flag_e,
            d.flag_f
        FROM latest_daily AS d
        LEFT JOIN volume_counts AS v
          ON d.gvkey = v.gvkey
         AND d.iid = v.iid
    ),

    latest_week_date AS (
        SELECT
            MAX(CAST(w.week_end_date AS DATE)) AS latest_week_end_date
        FROM read_parquet({weekly_paths}, union_by_name = true) AS w
        CROSS JOIN latest_daily_date AS ld
        WHERE CAST(w.week_end_date AS DATE) <= ld.screening_date
    ),

    latest_weekly AS (
        SELECT
            w.gvkey,
            w.iid,
            CAST(w.week_start_date AS DATE) AS week_start_date,
            CAST(w.week_end_date AS DATE) AS week_end_date,
            w.weekly_close_price,
            w.wma5,
            w.wma10,
            w.wma30,

            CASE
                WHEN w.wma5 IS NOT NULL
                 AND w.wma10 IS NOT NULL
                 AND w.wma30 IS NOT NULL
                THEN (
                    GREATEST(w.wma5, w.wma10, w.wma30)
                    - LEAST(w.wma5, w.wma10, w.wma30)
                ) / NULLIF((w.wma5 + w.wma10 + w.wma30) / 3, 0)
                ELSE NULL
            END AS weekly_ma_cluster_ratio,

            w.flag_g,
            w.flag_h
        FROM read_parquet({weekly_paths}, union_by_name = true) AS w
        CROSS JOIN latest_week_date AS lwd
        WHERE CAST(w.week_end_date AS DATE) = lwd.latest_week_end_date
    ),

    annual_recent AS (
        SELECT
            *
        FROM read_parquet('{annual_growth_path}')
        WHERE annual_rank_desc <= {annual_years}
    ),

    annual_flags_base AS (
        SELECT
            gvkey,

            MAX(CASE WHEN annual_rank_desc = 1 THEN fyear END) AS latest_annual_fyear,
            MAX(CASE WHEN annual_rank_desc = 1 THEN datadate END) AS latest_annual_datadate,

            COUNT(annual_revenue_growth_yoy) AS annual_revenue_growth_obs,
            COUNT(annual_operating_income_growth_yoy) AS annual_operating_income_growth_obs,

            MIN(annual_revenue_growth_yoy) AS annual_min_revenue_growth,
            MIN(annual_operating_income_growth_yoy) AS annual_min_operating_income_growth
        FROM annual_recent
        GROUP BY gvkey
    ),

    annual_flags AS (
        SELECT
            *,
            CASE
                WHEN annual_revenue_growth_obs = {annual_years}
                 AND annual_operating_income_growth_obs = {annual_years}
                 AND annual_min_revenue_growth >= {n}
                 AND annual_min_operating_income_growth >= {n}
                THEN TRUE ELSE FALSE
            END AS flag_a
        FROM annual_flags_base
    ),

    quarterly_recent AS (
        SELECT
            *
        FROM read_parquet('{quarterly_growth_path}')
        WHERE quarterly_rank_desc <= {quarter_count}
    ),

    quarterly_flags_base AS (
        SELECT
            gvkey,

            MAX(CASE WHEN quarterly_rank_desc = 1 THEN datadate END)
                AS latest_quarterly_datadate,

            MAX(CASE WHEN quarterly_rank_desc = 1 THEN fyearq END)
                AS latest_fyearq,

            MAX(CASE WHEN quarterly_rank_desc = 1 THEN fqtr END)
                AS latest_fqtr,

            COUNT(quarterly_revenue_growth_yoy)
                AS quarterly_revenue_growth_obs,

            COUNT(quarterly_operating_income_growth_yoy)
                AS quarterly_operating_income_growth_obs,

            MIN(quarterly_revenue_growth_yoy)
                AS quarterly_min_revenue_growth,

            MIN(quarterly_operating_income_growth_yoy)
                AS quarterly_min_operating_income_growth
        FROM quarterly_recent
        GROUP BY gvkey
    ),

    quarterly_flags AS (
        SELECT
            *,
            CASE
                WHEN quarterly_revenue_growth_obs = {quarter_count}
                 AND quarterly_operating_income_growth_obs = {quarter_count}
                 AND quarterly_min_revenue_growth >= {n}
                 AND quarterly_min_operating_income_growth >= {n}
                THEN TRUE ELSE FALSE
            END AS flag_b
        FROM quarterly_flags_base
    ),

    combined AS (
        SELECT
            d.screening_date,
            d.gvkey,
            d.iid,
            d.ticker,
            d.company_name,
            d.currency,

            {args.n_pct} AS n_pct,
            {annual_years} AS annual_years,
            {quarter_count} AS quarter_count,
            {q} AS q,
            {m} AS m,

            d.adjusted_close_price,
            d.close_price_raw,
            d.volume,
            d.volume_ma30,
            d.volume_ratio,

            d.flag_c,
            d.surge_day_count_3m,
            d.flag_d,

            d.ma20,
            d.ma50,
            d.ma100,
            d.daily_ma_cluster_ratio,
            d.flag_e,
            d.flag_f,

            w.week_start_date,
            w.week_end_date,
            w.weekly_close_price,
            w.wma5,
            w.wma10,
            w.wma30,
            w.weekly_ma_cluster_ratio,
            COALESCE(w.flag_g, FALSE) AS flag_g,
            COALESCE(w.flag_h, FALSE) AS flag_h,

            a.latest_annual_fyear,
            a.latest_annual_datadate,
            a.annual_revenue_growth_obs,
            a.annual_operating_income_growth_obs,
            a.annual_min_revenue_growth,
            a.annual_min_operating_income_growth,
            COALESCE(a.flag_a, FALSE) AS flag_a,

            b.latest_quarterly_datadate,
            b.latest_fyearq,
            b.latest_fqtr,
            b.quarterly_revenue_growth_obs,
            b.quarterly_operating_income_growth_obs,
            b.quarterly_min_revenue_growth,
            b.quarterly_min_operating_income_growth,
            COALESCE(b.flag_b, FALSE) AS flag_b,

            CASE
                WHEN COALESCE(a.flag_a, FALSE)
                 AND COALESCE(b.flag_b, FALSE)
                THEN TRUE ELSE FALSE
            END AS flag_ab,

            CASE
                WHEN d.flag_c
                 AND d.flag_d
                THEN TRUE ELSE FALSE
            END AS flag_cd,

            CASE
                WHEN COALESCE(a.flag_a, FALSE)
                 AND COALESCE(b.flag_b, FALSE)
                 AND d.flag_c
                 AND d.flag_d
                 AND d.flag_f
                 AND COALESCE(w.flag_h, FALSE)
                THEN TRUE ELSE FALSE
            END AS flag_all,

            TIMESTAMP '{created_at}' AS created_at

        FROM daily_result AS d
        LEFT JOIN latest_weekly AS w
          ON d.gvkey = w.gvkey
         AND d.iid = w.iid
        LEFT JOIN annual_flags AS a
          ON d.gvkey = a.gvkey
        LEFT JOIN quarterly_flags AS b
          ON d.gvkey = b.gvkey
    )

    SELECT
        *
    FROM combined
    ORDER BY
        flag_all DESC,
        flag_ab DESC,
        flag_cd DESC,
        flag_f DESC,
        flag_h DESC,
        volume_ratio DESC NULLS LAST,
        ticker
    """

    unfiltered_df = add_universe_filter_columns(con.execute(query).fetchdf())
    excluded_df = unfiltered_df[unfiltered_df["is_excluded_universe"]].copy()

    if args.disable_universe_filter:
        df = unfiltered_df.copy()
        print("WARNING: universe quality filter is disabled. Main output is unfiltered.")
    else:
        df = unfiltered_df[~unfiltered_df["is_excluded_universe"]].copy()

    param_tag = (
        f"n{int(args.n_pct)}"
        f"_annual{annual_years}"
        f"_quarter{quarter_count}"
        f"_q{int(q)}"
        f"_m{m}"
    )

    print("=" * 80)
    print("Final screening result summary")
    print(f"Input rows before universe filter: {len(unfiltered_df):,}")
    print(f"Excluded universe rows: {len(excluded_df):,}")
    print(f"Final output rows: {len(df):,}")
    print(f"Screening date: {df['screening_date'].max()}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"Flag counts before filtering: {flag_counts(unfiltered_df)}")
    print(f"Flag counts after filtering: {flag_counts(df)}")

    reason_counts = exclusion_reason_counts(excluded_df)
    print(f"Top exclusion reasons: {reason_counts}")
    if len(excluded_df) > 0:
        excluded_ratio = len(excluded_df) / len(unfiltered_df) if len(unfiltered_df) else 0
        print(
            "WARNING: universe filter excluded "
            f"{len(excluded_df):,} rows ({excluded_ratio:.2%}). "
            "Review excluded_universe audit files for SPAC/redeemable/security-type matches."
        )

    print("\nTop flag_all candidates:")
    top_cols = [
        "screening_date",
        "ticker",
        "company_name",
        "adjusted_close_price",
        "volume_ratio",
        "surge_day_count_3m",
        "annual_min_revenue_growth",
        "annual_min_operating_income_growth",
        "quarterly_min_revenue_growth",
        "quarterly_min_operating_income_growth",
        "flag_a",
        "flag_b",
        "flag_c",
        "flag_d",
        "flag_f",
        "flag_h",
        "flag_all",
    ]
    print(df[df["flag_all"]][top_cols].head(30).to_string(index=False))

    s3_base = f"{SCREENING_RESULTS_PREFIX}/{param_tag}"
    parquet_key = f"{s3_base}/screening_results.parquet"
    csv_key = f"{s3_base}/screening_results.csv"
    summary_key = f"{s3_base}/screening_summary.json"
    excluded_parquet_key = f"{s3_base}/excluded_universe/excluded_universe.parquet"
    excluded_csv_key = f"{s3_base}/excluded_universe/excluded_universe.csv"
    unfiltered_parquet_key = f"{s3_base}/unfiltered/screening_results_unfiltered.parquet"
    unfiltered_csv_key = f"{s3_base}/unfiltered/screening_results_unfiltered.csv"

    upload_df_to_s3_parquet(df, parquet_key)
    upload_df_to_s3_csv(df, csv_key)
    upload_df_to_s3_parquet(excluded_df, excluded_parquet_key)
    upload_df_to_s3_csv(excluded_df, excluded_csv_key)
    upload_json_to_s3(
        build_screening_summary(
            unfiltered_df=unfiltered_df,
            filtered_df=df,
            excluded_df=excluded_df,
            universe_filter_enabled=not args.disable_universe_filter,
        ),
        summary_key,
    )

    if args.write_unfiltered_audit:
        upload_df_to_s3_parquet(unfiltered_df, unfiltered_parquet_key)
        upload_df_to_s3_csv(unfiltered_df, unfiltered_csv_key)
        print(f"Uploaded unfiltered parquet to s3://{S3_BUCKET}/{unfiltered_parquet_key}")
        print(f"Uploaded unfiltered csv to s3://{S3_BUCKET}/{unfiltered_csv_key}")

    print(f"Uploaded parquet to s3://{S3_BUCKET}/{parquet_key}")
    print(f"Uploaded csv to s3://{S3_BUCKET}/{csv_key}")
    print(f"Uploaded excluded universe parquet to s3://{S3_BUCKET}/{excluded_parquet_key}")
    print(f"Uploaded excluded universe csv to s3://{S3_BUCKET}/{excluded_csv_key}")
    print(f"Uploaded screening summary to s3://{S3_BUCKET}/{summary_key}")
    print("Done.")


if __name__ == "__main__":
    main()
