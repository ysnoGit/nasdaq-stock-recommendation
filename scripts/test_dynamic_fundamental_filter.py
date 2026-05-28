import argparse
from pathlib import Path

import pandas as pd


ANNUAL_PATH = Path(
    "data/processed/annual_fundamental_growth_history/"
    "annual_fundamental_growth_history.parquet"
)

QUARTERLY_PATH = Path(
    "data/processed/quarterly_fundamental_growth_history/"
    "quarterly_fundamental_growth_history.parquet"
)

OUTPUT_DIR = Path("data/test_results")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test dynamic A/B fundamental screening logic."
    )
    parser.add_argument(
        "--n-pct",
        type=float,
        default=10.0,
        help="Growth threshold percentage. Example: 10 means 10%%.",
    )
    parser.add_argument(
        "--annual-years",
        type=int,
        default=3,
        help="Number of recent annual YoY growth periods to check.",
    )
    parser.add_argument(
        "--quarter-count",
        type=int,
        default=4,
        help="Number of recent quarterly YoY growth periods to check.",
    )

    args = parser.parse_args()

    n = args.n_pct / 100
    annual_years = args.annual_years
    quarter_count = args.quarter_count

    annual = pd.read_parquet(ANNUAL_PATH)
    quarterly = pd.read_parquet(QUARTERLY_PATH)

    # Latest company identity. Prefer quarterly identity because it is more recent.
    annual_identity = (
        annual[annual["annual_rank_desc"] == 1][
            ["gvkey", "ticker", "company_name", "currency"]
        ]
        .rename(
            columns={
                "ticker": "annual_ticker",
                "company_name": "annual_company_name",
                "currency": "annual_currency",
            }
        )
        .drop_duplicates("gvkey")
    )

    quarterly_identity = (
        quarterly[quarterly["quarterly_rank_desc"] == 1][
            ["gvkey", "ticker", "company_name", "currency"]
        ]
        .rename(
            columns={
                "ticker": "quarterly_ticker",
                "company_name": "quarterly_company_name",
                "currency": "quarterly_currency",
            }
        )
        .drop_duplicates("gvkey")
    )

    identity = annual_identity.merge(quarterly_identity, on="gvkey", how="outer")
    identity["ticker"] = identity["quarterly_ticker"].combine_first(
        identity["annual_ticker"]
    )
    identity["company_name"] = identity["quarterly_company_name"].combine_first(
        identity["annual_company_name"]
    )
    identity["currency"] = identity["quarterly_currency"].combine_first(
        identity["annual_currency"]
    )

    identity = identity[["gvkey", "ticker", "company_name", "currency"]]

    # Dynamic A condition:
    # Recent annual_years YoY growth records must all exceed n.
    annual_recent = annual[annual["annual_rank_desc"] <= annual_years].copy()

    annual_flags = (
        annual_recent.groupby("gvkey", dropna=False)
        .agg(
            annual_revenue_growth_obs=("annual_revenue_growth_yoy", "count"),
            annual_operating_income_growth_obs=(
                "annual_operating_income_growth_yoy",
                "count",
            ),
            annual_min_revenue_growth=("annual_revenue_growth_yoy", "min"),
            annual_min_operating_income_growth=(
                "annual_operating_income_growth_yoy",
                "min",
            ),
            latest_annual_fyear=("fyear", "max"),
        )
        .reset_index()
    )

    annual_flags["flag_a"] = (
        (annual_flags["annual_revenue_growth_obs"] == annual_years)
        & (annual_flags["annual_operating_income_growth_obs"] == annual_years)
        & (annual_flags["annual_min_revenue_growth"] >= n)
        & (annual_flags["annual_min_operating_income_growth"] >= n)
    )

    # Dynamic B condition:
    # Recent quarter_count YoY quarterly growth records must all exceed n.
    quarterly_recent = quarterly[
        quarterly["quarterly_rank_desc"] <= quarter_count
    ].copy()

    quarterly_flags = (
        quarterly_recent.groupby("gvkey", dropna=False)
        .agg(
            quarterly_revenue_growth_obs=("quarterly_revenue_growth_yoy", "count"),
            quarterly_operating_income_growth_obs=(
                "quarterly_operating_income_growth_yoy",
                "count",
            ),
            quarterly_min_revenue_growth=("quarterly_revenue_growth_yoy", "min"),
            quarterly_min_operating_income_growth=(
                "quarterly_operating_income_growth_yoy",
                "min",
            ),
            latest_quarterly_datadate=("datadate", "max"),
        )
        .reset_index()
    )

    quarterly_flags["flag_b"] = (
        (quarterly_flags["quarterly_revenue_growth_obs"] == quarter_count)
        & (quarterly_flags["quarterly_operating_income_growth_obs"] == quarter_count)
        & (quarterly_flags["quarterly_min_revenue_growth"] >= n)
        & (quarterly_flags["quarterly_min_operating_income_growth"] >= n)
    )

    result = (
        identity.merge(annual_flags, on="gvkey", how="left")
        .merge(quarterly_flags, on="gvkey", how="left")
    )

    result["flag_a"] = result["flag_a"].fillna(False)
    result["flag_b"] = result["flag_b"].fillna(False)
    result["flag_ab"] = result["flag_a"] & result["flag_b"]

    result = result.sort_values(
        by=[
            "flag_ab",
            "flag_a",
            "flag_b",
            "annual_min_revenue_growth",
            "quarterly_min_revenue_growth",
        ],
        ascending=[False, False, False, False, False],
    )

    output_file = (
        OUTPUT_DIR
        / f"dynamic_fundamental_test_n{int(args.n_pct)}"
          f"_annual{annual_years}_quarter{quarter_count}.csv"
    )
    result.to_csv(output_file, index=False)

    print("=" * 80)
    print("Dynamic fundamental screening test")
    print(f"n threshold: {args.n_pct:.2f}%")
    print(f"annual_years: {annual_years}")
    print(f"quarter_count: {quarter_count}")
    print("=" * 80)
    print(f"Total companies: {len(result):,}")
    print(f"flag_a count: {result['flag_a'].sum():,}")
    print(f"flag_b count: {result['flag_b'].sum():,}")
    print(f"flag_a AND flag_b count: {result['flag_ab'].sum():,}")
    print(f"Saved result: {output_file}")

    print("\nTop A and B candidates:")
    cols = [
        "gvkey",
        "ticker",
        "company_name",
        "latest_annual_fyear",
        "latest_quarterly_datadate",
        "annual_revenue_growth_obs",
        "annual_operating_income_growth_obs",
        "annual_min_revenue_growth",
        "annual_min_operating_income_growth",
        "quarterly_revenue_growth_obs",
        "quarterly_operating_income_growth_obs",
        "quarterly_min_revenue_growth",
        "quarterly_min_operating_income_growth",
        "flag_a",
        "flag_b",
        "flag_ab",
    ]

    print(result[result["flag_ab"]][cols].head(30).to_string(index=False))


if __name__ == "__main__":
    main()
