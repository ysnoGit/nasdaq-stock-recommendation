from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from condition_backtest_lab.src.config import SP500_BENCHMARK_PATH
from server_pipeline.utils.wrds_connection import get_wrds_connection

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local convenience
    load_dotenv = None


SP500_GVKEYX = "000003"


def extract_sp500_benchmark(
    output_path: Path = SP500_BENCHMARK_PATH,
    start_date: str = "1983-12-30",
    end_date: str | None = None,
) -> pd.DataFrame:
    if load_dotenv is not None:
        load_dotenv()

    end_filter = f"and datadate <= '{end_date}'" if end_date else ""
    query = f"""
        select
            datadate as benchmark_date,
            gvkeyx,
            newnum,
            oldnum,
            prccd as sp500_price_close,
            prccddiv as sp500_total_return_index,
            prchd as sp500_high,
            prcld as sp500_low
        from comp.idx_daily
        where gvkeyx = '{SP500_GVKEYX}'
          and datadate >= '{start_date}'
          {end_filter}
        order by datadate
    """

    print("Connecting to WRDS...")
    conn = get_wrds_connection()
    try:
        df = conn.raw_sql(query, date_cols=["benchmark_date"])
    finally:
        conn.close()
        print("WRDS connection closed.")

    if df.empty:
        raise RuntimeError("No S&P 500 benchmark rows returned from WRDS comp.idx_daily.")

    df["gvkeyx"] = df["gvkeyx"].astype(str).str.zfill(6)
    df["data_source"] = "wrds_comp_idx_daily"
    df["created_at"] = datetime.now(timezone.utc)

    duplicate_count = df.duplicated(subset=["benchmark_date"]).sum()
    if duplicate_count:
        raise RuntimeError(f"Found {duplicate_count:,} duplicate benchmark_date rows.")

    if df["sp500_price_close"].isna().any():
        missing = int(df["sp500_price_close"].isna().sum())
        raise RuntimeError(f"S&P 500 price close has {missing:,} missing rows.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False, compression="zstd")
    return df


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract S&P 500 daily benchmark data from WRDS comp.idx_daily."
    )
    parser.add_argument("--output-path", type=Path, default=SP500_BENCHMARK_PATH)
    parser.add_argument("--start-date", default="1983-12-30")
    parser.add_argument("--end-date", default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    df = extract_sp500_benchmark(args.output_path, args.start_date, args.end_date)
    print(f"S&P 500 benchmark parquet: {args.output_path.resolve()}")
    print(f"Rows: {len(df):,}")
    print(f"Date range: {df['benchmark_date'].min().date()} to {df['benchmark_date'].max().date()}")
    print(f"GVKEYX values: {', '.join(sorted(df['gvkeyx'].unique()))}")
    print(f"Price close non-null rows: {df['sp500_price_close'].notna().sum():,}")
    print(f"Total-return non-null rows: {df['sp500_total_return_index'].notna().sum():,}")
    latest = df.tail(3)[
        ["benchmark_date", "sp500_price_close", "sp500_total_return_index"]
    ]
    print("Latest rows:")
    print(latest.to_string(index=False))


if __name__ == "__main__":
    main()
