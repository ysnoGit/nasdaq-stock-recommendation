import argparse
import os
from pathlib import Path
from datetime import datetime, timezone

import boto3
import duckdb
from dotenv import load_dotenv


load_dotenv()

S3_BUCKET = os.environ["S3_BUCKET"]

DAILY_PATH = Path(
    "data/processed/daily_market_metrics/"
    "daily_market_metrics.parquet"
)

WEEKLY_PATH = Path(
    "data/processed/weekly_market_metrics/"
    "weekly_market_metrics.parquet"
)

ANNUAL_GROWTH_PATH = Path(
    "data/processed/annual_fundamental_growth_history/"
    "annual_fundamental_growth_history.parquet"
)

QUARTERLY_GROWTH_PATH = Path(
    "data/processed/quarterly_fundamental_growth_history/"
    "quarterly_fundamental_growth_history.parquet"
)

OUTPUT_DIR = Path("data/results/screening_results")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def upload_file_to_s3(local_path: Path, s3_key: str) -> None:
    s3 = boto3.client("s3")
    print(f"Uploading: {local_path}")
    print(f"To: s3://{S3_BUCKET}/{s3_key}")
    s3.upload_file(str(local_path), S3_BUCKET, s3_key)


def check_required_files() -> None:
    required_files = [
        DAILY_PATH,
        WEEKLY_PATH,
        ANNUAL_GROWTH_PATH,
        QUARTERLY_GROWTH_PATH,
    ]

    missing = [path for path in required_files if not path.exists()]

    if missing:
        missing_text = "\n".join(str(path) for path in missing)
        raise FileNotFoundError(
            "Missing required processed files:\n"
            f"{missing_text}\n\n"
            "Run the previous build scripts first."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build final NASDAQ stock screening results."
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

    args = parser.parse_args()

    check_required_files()

    n = args.n_pct / 100.0
    annual_years = args.annual_years
    quarter_count = args.quarter_count
    q = args.q
    m = args.m

    created_at = datetime.now(timezone.utc).isoformat()

    print("=" * 80)
    print("Building final screening results")
    print(f"n threshold: {args.n_pct:.2f}%")
    print(f"annual_years: {annual_years}")
    print(f"quarter_count: {quarter_count}")
    print(f"q volume multiple: {q}")
    print(f"m surge count: {m}")
    print("=" * 80)

    con = duckdb.connect()

    query = f"""
    WITH latest_daily_date AS (
        SELECT
            MAX(CAST(date AS DATE)) AS screening_date
        FROM read_parquet('{DAILY_PATH}')
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
        FROM read_parquet('{DAILY_PATH}') AS d
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
        FROM read_parquet('{WEEKLY_PATH}') AS w
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
        FROM read_parquet('{WEEKLY_PATH}') AS w
        CROSS JOIN latest_week_date AS lwd
        WHERE CAST(w.week_end_date AS DATE) = lwd.latest_week_end_date
    ),

    annual_recent AS (
        SELECT
            *
        FROM read_parquet('{ANNUAL_GROWTH_PATH}')
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
        FROM read_parquet('{QUARTERLY_GROWTH_PATH}')
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

            -- User parameters used for this result.
            {args.n_pct} AS n_pct,
            {annual_years} AS annual_years,
            {quarter_count} AS quarter_count,
            {q} AS q,
            {m} AS m,

            -- Latest daily metrics.
            d.adjusted_close_price,
            d.close_price_raw,
            d.volume,
            d.volume_ma30,
            d.volume_ratio,

            -- C/D.
            d.flag_c,
            d.surge_day_count_3m,
            d.flag_d,

            -- E/F.
            d.ma20,
            d.ma50,
            d.ma100,
            d.daily_ma_cluster_ratio,
            d.flag_e,
            d.flag_f,

            -- G/H.
            w.week_start_date,
            w.week_end_date,
            w.weekly_close_price,
            w.wma5,
            w.wma10,
            w.wma30,
            w.weekly_ma_cluster_ratio,
            COALESCE(w.flag_g, FALSE) AS flag_g,
            COALESCE(w.flag_h, FALSE) AS flag_h,

            -- A.
            a.latest_annual_fyear,
            a.latest_annual_datadate,
            a.annual_revenue_growth_obs,
            a.annual_operating_income_growth_obs,
            a.annual_min_revenue_growth,
            a.annual_min_operating_income_growth,
            COALESCE(a.flag_a, FALSE) AS flag_a,

            -- B.
            b.latest_quarterly_datadate,
            b.latest_fyearq,
            b.latest_fqtr,
            b.quarterly_revenue_growth_obs,
            b.quarterly_operating_income_growth_obs,
            b.quarterly_min_revenue_growth,
            b.quarterly_min_operating_income_growth,
            COALESCE(b.flag_b, FALSE) AS flag_b,

            -- Combined flags.
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

    df = con.execute(query).fetchdf()

    param_tag = (
        f"n{int(args.n_pct)}"
        f"_annual{annual_years}"
        f"_quarter{quarter_count}"
        f"_q{int(q)}"
        f"_m{m}"
    )

    parquet_file = OUTPUT_DIR / f"screening_results_{param_tag}.parquet"
    csv_file = OUTPUT_DIR / f"screening_results_{param_tag}.csv"

    df.to_parquet(parquet_file, index=False)
    df.to_csv(csv_file, index=False)

    print("=" * 80)
    print("Final screening result summary")
    print(f"Output rows: {len(df):,}")
    print(f"Screening date: {df['screening_date'].max()}")
    print(f"Unique tickers: {df['ticker'].nunique():,}")
    print(f"flag_a count: {df['flag_a'].sum():,}")
    print(f"flag_b count: {df['flag_b'].sum():,}")
    print(f"flag_ab count: {df['flag_ab'].sum():,}")
    print(f"flag_c count: {df['flag_c'].sum():,}")
    print(f"flag_d count: {df['flag_d'].sum():,}")
    print(f"flag_cd count: {df['flag_cd'].sum():,}")
    print(f"flag_e count: {df['flag_e'].sum():,}")
    print(f"flag_f count: {df['flag_f'].sum():,}")
    print(f"flag_g count: {df['flag_g'].sum():,}")
    print(f"flag_h count: {df['flag_h'].sum():,}")
    print(f"flag_all count: {df['flag_all'].sum():,}")
    print(f"Saved parquet: {parquet_file}")
    print(f"Saved csv: {csv_file}")

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

    s3_base = f"results/screening_results/{param_tag}"

    upload_file_to_s3(
        parquet_file,
        f"{s3_base}/screening_results.parquet",
    )

    upload_file_to_s3(
        csv_file,
        f"{s3_base}/screening_results.csv",
    )

    print("Done.")


if __name__ == "__main__":
    main()
