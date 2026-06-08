from __future__ import annotations

import argparse
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
import sys
from typing import Any

import boto3
import duckdb
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtest_lab.src.build_backtest_daily_features import (  # noqa: E402
    build_backtest_daily_features,
    build_backtest_security_master,
)
from backtest_lab.src.build_backtest_weekly_features import build_backtest_weekly_features  # noqa: E402
from backtest_lab.src.config import (  # noqa: E402
    BACKTEST_END_DATE,
    BACKTEST_START_DATE,
    BACKTEST_WARMUP_CALENDAR_DAYS,
    parse_date,
)
from backtest_lab.src.db import (  # noqa: E402
    apply_sql_file,
    connect_supabase,
    normalize_records,
    require_tables,
)
from backtest_lab.src.materialize_result_tables import materialize_result_tables  # noqa: E402
from backtest_lab.src.parameter_grid import grid_parameter_names  # noqa: E402
from server_pipeline.config import (  # noqa: E402
    ANNUAL_GROWTH_HISTORY_PREFIX,
    QUARTERLY_GROWTH_HISTORY_PREFIX,
    S3_BUCKET,
)


BACKTEST_ROOT = Path(__file__).resolve().parents[1]
ANNUAL_GROWTH_S3_PATH = (
    f"s3://{S3_BUCKET}/{ANNUAL_GROWTH_HISTORY_PREFIX}/"
    "annual_fundamental_growth_history.parquet"
)
QUARTERLY_GROWTH_S3_PATH = (
    f"s3://{S3_BUCKET}/{QUARTERLY_GROWTH_HISTORY_PREFIX}/"
    "quarterly_fundamental_growth_history.parquet"
)

SELECTION_COLUMNS = [
    "parameter_set_id",
    "screen_type",
    "selected_date",
    "gvkey",
    "iid",
    "ticker",
    "company_name",
    "selected_price",
    "selected_adjusted_price",
    "flag_a",
    "flag_b",
    "flag_c",
    "flag_d",
    "flag_e",
    "flag_f",
    "flag_g",
    "flag_h",
]

PRICE_FLOW_COLUMNS = [
    "selection_event_id",
    "period_index",
    "period_start_date",
    "period_end_date",
    "trading_days",
    "start_price",
    "end_price",
    "high_price",
    "low_price",
    "avg_price",
    "return_pct",
]


def parse_s3_uri(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Expected S3 URI, got: {uri}")
    bucket, key = uri[5:].split("/", 1)
    return bucket, key


def read_s3_parquet(uri: str) -> pd.DataFrame:
    bucket, key = parse_s3_uri(uri)
    response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(BytesIO(response["Body"].read()))


def fetch_grid_parameters(conn, names: list[str]) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                parameter_set_id,
                parameter_set_name,
                start_date,
                end_date,
                annual_growth_pct,
                quarterly_growth_pct,
                annual_years,
                quarter_count,
                volume_ratio_threshold,
                volume_surge_min_days,
                daily_ma_tolerance_pct,
                weekly_ma_tolerance_pct
            FROM backtest_parameter_set
            WHERE parameter_set_name = ANY(%s)
            ORDER BY parameter_set_name
            """,
            (names,),
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]

    params = pd.DataFrame(rows, columns=columns)
    if len(params) != len(names):
        found = set(params["parameter_set_name"].tolist())
        missing = sorted(set(names) - found)
        raise RuntimeError(f"Missing backtest parameter sets: {missing}")
    return params


def load_growth_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    print(f"Reading annual growth history from {ANNUAL_GROWTH_S3_PATH}")
    annual = read_s3_parquet(ANNUAL_GROWTH_S3_PATH)
    print(f"Annual growth rows: {len(annual):,}")

    print(f"Reading quarterly growth history from {QUARTERLY_GROWTH_S3_PATH}")
    quarterly = read_s3_parquet(QUARTERLY_GROWTH_S3_PATH)
    print(f"Quarterly growth rows: {len(quarterly):,}")

    annual = annual.rename(
        columns={
            "annual_revenue_growth_yoy": "annual_revenue_growth",
            "annual_operating_income_growth_yoy": "annual_operating_income_growth",
        }
    )
    quarterly = quarterly.rename(
        columns={
            "quarterly_revenue_growth_yoy": "quarterly_revenue_growth",
            "quarterly_operating_income_growth_yoy": "quarterly_operating_income_growth",
        }
    )

    annual["datadate"] = pd.to_datetime(annual["datadate"]).dt.date
    quarterly["datadate"] = pd.to_datetime(quarterly["datadate"]).dt.date
    annual["gvkey"] = annual["gvkey"].astype(str)
    quarterly["gvkey"] = quarterly["gvkey"].astype(str)
    return annual, quarterly


def prepare_duckdb(
    daily: pd.DataFrame,
    weekly: pd.DataFrame,
    master: pd.DataFrame,
    annual: pd.DataFrame,
    quarterly: pd.DataFrame,
) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("PRAGMA threads=4")
    con.register("daily_df", daily)
    con.register("weekly_df", weekly)
    con.register("master_df", master)
    con.register("annual_df", annual)
    con.register("quarterly_df", quarterly)
    con.execute("CREATE TEMP TABLE daily AS SELECT * FROM daily_df")
    con.execute("CREATE TEMP TABLE weekly AS SELECT * FROM weekly_df")
    con.execute("CREATE TEMP TABLE master AS SELECT * FROM master_df")
    con.execute("CREATE TEMP TABLE annual AS SELECT * FROM annual_df")
    con.execute("CREATE TEMP TABLE quarterly AS SELECT * FROM quarterly_df")
    con.execute("CREATE INDEX daily_security_date_idx ON daily(gvkey, iid, snapshot_date)")
    con.execute("CREATE INDEX weekly_security_date_idx ON weekly(gvkey, iid, week_end_date)")
    con.execute("CREATE INDEX annual_security_date_idx ON annual(gvkey, datadate)")
    con.execute("CREATE INDEX quarterly_security_date_idx ON quarterly(gvkey, datadate)")
    return con


def sql_literal(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    if hasattr(value, "isoformat"):
        return f"DATE '{value.isoformat()}'"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def build_selection_for_parameter(con: duckdb.DuckDBPyConnection, parameter: pd.Series) -> pd.DataFrame:
    p = parameter.to_dict()
    start_date = p["start_date"]
    end_date = p["end_date"]
    end_filter = (
        ""
        if end_date is None or pd.isna(end_date)
        else f"AND d.snapshot_date <= {sql_literal(end_date)}"
    )
    query = f"""
    WITH candidate_daily AS (
        SELECT
            {int(p["parameter_set_id"])} AS parameter_set_id,
            d.snapshot_date,
            d.gvkey,
            d.iid,
            m.ticker,
            m.company_name,
            d.close_price,
            d.adjusted_close_price,
            TRUE AS flag_c,
            recent_volume.surge_days >= {int(p["volume_surge_min_days"])} AS flag_d,
            TRUE AS flag_e,
            TRUE AS flag_f
        FROM daily d
        LEFT JOIN master m
          ON m.gvkey = d.gvkey
         AND m.iid = d.iid
        JOIN LATERAL (
            SELECT COUNT(*) FILTER (
                WHERE hist.volume_ratio >= {float(p["volume_ratio_threshold"])}
            )::integer AS surge_days
            FROM daily hist
            WHERE hist.gvkey = d.gvkey
              AND hist.iid = d.iid
              AND hist.snapshot_date BETWEEN d.snapshot_date - INTERVAL 3 MONTH
                                        AND d.snapshot_date
        ) recent_volume ON true
        WHERE d.snapshot_date >= {sql_literal(start_date)}
          {end_filter}
          AND d.volume_ratio >= {float(p["volume_ratio_threshold"])}
          AND d.ma20 IS NOT NULL
          AND d.ma50 IS NOT NULL
          AND d.ma100 IS NOT NULL
          AND d.ma50 <> 0
          AND d.ma100 <> 0
          AND d.ma20 / d.ma50 BETWEEN 1 - {float(p["daily_ma_tolerance_pct"])} / 100.0
                                AND 1 + {float(p["daily_ma_tolerance_pct"])} / 100.0
          AND d.ma20 / d.ma100 BETWEEN 1 - {float(p["daily_ma_tolerance_pct"])} / 100.0
                                 AND 1 + {float(p["daily_ma_tolerance_pct"])} / 100.0
          AND d.ma50 / d.ma100 BETWEEN 1 - {float(p["daily_ma_tolerance_pct"])} / 100.0
                                 AND 1 + {float(p["daily_ma_tolerance_pct"])} / 100.0
          AND d.future_daily_ma20 IS NOT NULL
          AND d.future_daily_ma50 IS NOT NULL
          AND d.future_daily_ma100 IS NOT NULL
          AND d.future_daily_ma50 <> 0
          AND d.future_daily_ma100 <> 0
          AND d.future_daily_ma20 / d.future_daily_ma50 BETWEEN 1 - {float(p["daily_ma_tolerance_pct"])} / 100.0
                                                         AND 1 + {float(p["daily_ma_tolerance_pct"])} / 100.0
          AND d.future_daily_ma20 / d.future_daily_ma100 BETWEEN 1 - {float(p["daily_ma_tolerance_pct"])} / 100.0
                                                          AND 1 + {float(p["daily_ma_tolerance_pct"])} / 100.0
          AND d.future_daily_ma50 / d.future_daily_ma100 BETWEEN 1 - {float(p["daily_ma_tolerance_pct"])} / 100.0
                                                          AND 1 + {float(p["daily_ma_tolerance_pct"])} / 100.0
    ),
    daily_with_fundamentals AS (
        SELECT
            c.*,
            (
                annual_check.valid_count = {int(p["annual_years"])}
                AND annual_check.pass_count = {int(p["annual_years"])}
            ) AS flag_a,
            (
                quarterly_check.valid_count = {int(p["quarter_count"])}
                AND quarterly_check.pass_count = {int(p["quarter_count"])}
            ) AS flag_b
        FROM candidate_daily c
        JOIN LATERAL (
            SELECT
                COUNT(*)::integer AS valid_count,
                COUNT(*) FILTER (
                    WHERE annual_revenue_growth >= {float(p["annual_growth_pct"])} / 100.0
                      AND annual_operating_income_growth >= {float(p["annual_growth_pct"])} / 100.0
                )::integer AS pass_count
            FROM (
                SELECT annual_revenue_growth, annual_operating_income_growth
                FROM (
                    SELECT
                        annual_revenue_growth,
                        annual_operating_income_growth,
                        ROW_NUMBER() OVER (ORDER BY a.datadate DESC) AS rn
                    FROM annual a
                    WHERE a.gvkey = c.gvkey
                      AND a.datadate <= c.snapshot_date
                      AND a.annual_revenue_growth IS NOT NULL
                      AND a.annual_operating_income_growth IS NOT NULL
                ) ranked_annual
                WHERE rn <= {int(p["annual_years"])}
            ) recent_annual
        ) annual_check ON true
        JOIN LATERAL (
            SELECT
                COUNT(*)::integer AS valid_count,
                COUNT(*) FILTER (
                    WHERE quarterly_revenue_growth >= {float(p["quarterly_growth_pct"])} / 100.0
                      AND quarterly_operating_income_growth >= {float(p["quarterly_growth_pct"])} / 100.0
                )::integer AS pass_count
            FROM (
                SELECT quarterly_revenue_growth, quarterly_operating_income_growth
                FROM (
                    SELECT
                        quarterly_revenue_growth,
                        quarterly_operating_income_growth,
                        ROW_NUMBER() OVER (ORDER BY q.datadate DESC) AS rn
                    FROM quarterly q
                    WHERE q.gvkey = c.gvkey
                      AND q.datadate <= c.snapshot_date
                      AND q.quarterly_revenue_growth IS NOT NULL
                      AND q.quarterly_operating_income_growth IS NOT NULL
                ) ranked_quarterly
                WHERE rn <= {int(p["quarter_count"])}
            ) recent_quarterly
        ) quarterly_check ON true
        WHERE c.flag_d
    ),
    af_candidates AS (
        SELECT
            parameter_set_id,
            'A_F' AS screen_type,
            snapshot_date AS selected_date,
            gvkey,
            iid,
            ticker,
            company_name,
            close_price AS selected_price,
            adjusted_close_price AS selected_adjusted_price,
            flag_a,
            flag_b,
            flag_c,
            flag_d,
            flag_e,
            flag_f,
            NULL::BOOLEAN AS flag_g,
            NULL::BOOLEAN AS flag_h,
            ROW_NUMBER() OVER (
                PARTITION BY parameter_set_id, gvkey, iid
                ORDER BY snapshot_date
            ) AS rn
        FROM daily_with_fundamentals
        WHERE flag_a AND flag_b
    ),
    ah_candidates AS (
        SELECT
            f.parameter_set_id,
            'A_H' AS screen_type,
            f.snapshot_date AS selected_date,
            f.gvkey,
            f.iid,
            f.ticker,
            f.company_name,
            f.close_price AS selected_price,
            f.adjusted_close_price AS selected_adjusted_price,
            f.flag_a,
            f.flag_b,
            f.flag_c,
            f.flag_d,
            f.flag_e,
            f.flag_f,
            TRUE AS flag_g,
            TRUE AS flag_h,
            ROW_NUMBER() OVER (
                PARTITION BY f.parameter_set_id, f.gvkey, f.iid
                ORDER BY f.snapshot_date
            ) AS rn
        FROM daily_with_fundamentals f
        JOIN weekly w
          ON w.week_end_date = f.snapshot_date
         AND w.gvkey = f.gvkey
         AND w.iid = f.iid
        WHERE f.flag_a
          AND f.flag_b
          AND w.weekly_ma5 IS NOT NULL
          AND w.weekly_ma10 IS NOT NULL
          AND w.weekly_ma30 IS NOT NULL
          AND w.weekly_ma10 <> 0
          AND w.weekly_ma30 <> 0
          AND w.weekly_ma5 / w.weekly_ma10 BETWEEN 1 - {float(p["weekly_ma_tolerance_pct"])} / 100.0
                                              AND 1 + {float(p["weekly_ma_tolerance_pct"])} / 100.0
          AND w.weekly_ma5 / w.weekly_ma30 BETWEEN 1 - {float(p["weekly_ma_tolerance_pct"])} / 100.0
                                              AND 1 + {float(p["weekly_ma_tolerance_pct"])} / 100.0
          AND w.weekly_ma10 / w.weekly_ma30 BETWEEN 1 - {float(p["weekly_ma_tolerance_pct"])} / 100.0
                                               AND 1 + {float(p["weekly_ma_tolerance_pct"])} / 100.0
          AND w.future_weekly_ma5 IS NOT NULL
          AND w.future_weekly_ma10 IS NOT NULL
          AND w.future_weekly_ma30 IS NOT NULL
          AND w.future_weekly_ma10 <> 0
          AND w.future_weekly_ma30 <> 0
          AND w.future_weekly_ma5 / w.future_weekly_ma10 BETWEEN 1 - {float(p["weekly_ma_tolerance_pct"])} / 100.0
                                                            AND 1 + {float(p["weekly_ma_tolerance_pct"])} / 100.0
          AND w.future_weekly_ma5 / w.future_weekly_ma30 BETWEEN 1 - {float(p["weekly_ma_tolerance_pct"])} / 100.0
                                                            AND 1 + {float(p["weekly_ma_tolerance_pct"])} / 100.0
          AND w.future_weekly_ma10 / w.future_weekly_ma30 BETWEEN 1 - {float(p["weekly_ma_tolerance_pct"])} / 100.0
                                                             AND 1 + {float(p["weekly_ma_tolerance_pct"])} / 100.0
    )
    SELECT {", ".join(SELECTION_COLUMNS)}
    FROM af_candidates
    WHERE rn = 1
    UNION ALL
    SELECT {", ".join(SELECTION_COLUMNS)}
    FROM ah_candidates
    WHERE rn = 1
    """
    out = con.execute(query).fetchdf()
    print(
        f"{p['parameter_set_name']}: selected {len(out):,} rows "
        f"({out['screen_type'].value_counts().to_dict() if not out.empty else {}})"
    )
    return out


def build_all_selections(con: duckdb.DuckDBPyConnection, parameters: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for _, parameter in parameters.iterrows():
        frame = build_selection_for_parameter(con, parameter)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=SELECTION_COLUMNS)
    selections = pd.concat(frames, ignore_index=True)
    selections["selected_date"] = pd.to_datetime(selections["selected_date"]).dt.date
    return selections


def insert_dataframe(conn, table: str, df: pd.DataFrame, columns: list[str]) -> None:
    if df.empty:
        print(f"No rows to insert into {table}.")
        return
    placeholders = ", ".join(["%s"] * len(columns))
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})"
    records = normalize_records(df[columns])
    chunk_size = 5_000
    with conn.cursor() as cur:
        for offset in range(0, len(records), chunk_size):
            cur.executemany(sql, records[offset : offset + chunk_size])


def delete_existing_backtest_outputs(conn, parameter_ids: list[int]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM backtest_price_flow_3m f
            USING backtest_selection_event e
            WHERE f.selection_event_id = e.selection_event_id
              AND e.parameter_set_id = ANY(%s)
            """,
            (parameter_ids,),
        )
        print(f"Deleted price-flow rows: {cur.rowcount:,}")
        cur.execute(
            "DELETE FROM backtest_selection_event WHERE parameter_set_id = ANY(%s)",
            (parameter_ids,),
        )
        print(f"Deleted selection rows: {cur.rowcount:,}")


def fetch_selection_id_map(conn, parameter_ids: list[int]) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                selection_event_id,
                parameter_set_id,
                screen_type,
                gvkey,
                iid
            FROM backtest_selection_event
            WHERE parameter_set_id = ANY(%s)
            """,
            (parameter_ids,),
        )
        rows = cur.fetchall()
        columns = [column.name for column in cur.description]
    return pd.DataFrame(rows, columns=columns)


def build_price_flow(con: duckdb.DuckDBPyConnection, selections_with_ids: pd.DataFrame) -> pd.DataFrame:
    if selections_with_ids.empty:
        return pd.DataFrame(columns=PRICE_FLOW_COLUMNS)

    con.register("selected_with_ids_df", selections_with_ids)
    query = """
    WITH selected AS (
        SELECT
            selection_event_id,
            selected_date,
            gvkey,
            iid
        FROM selected_with_ids_df
    ),
    latest_daily AS (
        SELECT MAX(snapshot_date) AS latest_snapshot_date
        FROM daily
    ),
    periods AS (
        SELECT
            s.selection_event_id,
            period_index,
            CAST(s.selected_date + period_index * INTERVAL 3 MONTH AS DATE) AS period_start_date,
            LEAST(
                CAST(s.selected_date + (period_index + 1) * INTERVAL 3 MONTH - INTERVAL 1 DAY AS DATE),
                l.latest_snapshot_date
            ) AS period_end_date,
            s.gvkey,
            s.iid
        FROM selected s
        CROSS JOIN latest_daily l
        CROSS JOIN range(
            0,
            CAST(CEIL(date_diff('day', s.selected_date, l.latest_snapshot_date) / 90.0) AS BIGINT) + 1
        ) AS gs(period_index)
        WHERE s.selected_date <= l.latest_snapshot_date
    ),
    priced AS (
        SELECT
            p.selection_event_id,
            p.period_index,
            p.period_start_date,
            p.period_end_date,
            d.snapshot_date,
            d.adjusted_close_price
        FROM periods p
        JOIN daily d
          ON d.gvkey = p.gvkey
         AND d.iid = p.iid
         AND d.snapshot_date BETWEEN p.period_start_date AND p.period_end_date
    ),
    aggregated AS (
        SELECT
            selection_event_id,
            period_index,
            period_start_date,
            period_end_date,
            COUNT(*)::integer AS trading_days,
            arg_min(adjusted_close_price, snapshot_date) AS start_price,
            arg_max(adjusted_close_price, snapshot_date) AS end_price,
            MAX(adjusted_close_price) AS high_price,
            MIN(adjusted_close_price) AS low_price,
            AVG(adjusted_close_price) AS avg_price
        FROM priced
        GROUP BY selection_event_id, period_index, period_start_date, period_end_date
    )
    SELECT
        selection_event_id,
        period_index,
        period_start_date,
        period_end_date,
        trading_days,
        start_price,
        end_price,
        high_price,
        low_price,
        avg_price,
        CASE
            WHEN start_price IS NOT NULL AND start_price <> 0
            THEN (end_price - start_price) / start_price * 100.0
            ELSE NULL
        END AS return_pct
    FROM aggregated
    ORDER BY selection_event_id, period_index
    """
    price_flow = con.execute(query).fetchdf()
    for column in ["period_start_date", "period_end_date"]:
        price_flow[column] = pd.to_datetime(price_flow[column]).dt.date
    print(f"Price-flow rows built locally: {len(price_flow):,}")
    return price_flow


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run historical backtest locally with S3/DuckDB inputs and load only "
            "final selections plus price-flow summaries into Supabase."
        )
    )
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--start-date", default=BACKTEST_START_DATE)
    parser.add_argument("--end-date", default=BACKTEST_END_DATE)
    parser.add_argument("--warmup-calendar-days", type=int, default=BACKTEST_WARMUP_CALENDAR_DAYS)
    parser.add_argument(
        "--parameter-set-name",
        help="Run one grid parameter set. If omitted, all 16 grid combinations run.",
    )
    args = parser.parse_args()

    parameter_names = [args.parameter_set_name] if args.parameter_set_name else grid_parameter_names()
    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date)

    print("Running S3/DuckDB backtest. Supabase will receive final outputs only.")
    print(f"Parameter sets: {len(parameter_names):,}")

    daily = build_backtest_daily_features(
        start_date=start_date,
        end_date=end_date,
        warmup_calendar_days=args.warmup_calendar_days,
    )
    master = build_backtest_security_master(daily)
    weekly = build_backtest_weekly_features(daily)
    annual, quarterly = load_growth_inputs()

    con = prepare_duckdb(daily, weekly, master, annual, quarterly)

    with connect_supabase() as supabase:
        if args.apply_schema:
            print("Applying backtest schema...")
            apply_sql_file(supabase, BACKTEST_ROOT / "sql" / "create_backtest_tables.sql")
        require_tables(
            supabase,
            [
                "backtest_parameter_set",
                "backtest_selection_event",
                "backtest_price_flow_3m",
            ],
        )
        parameters = fetch_grid_parameters(supabase, parameter_names)

    selections = build_all_selections(con, parameters)
    if selections.empty:
        print("No selections produced for the requested parameter sets.")

    parameter_ids = [int(value) for value in parameters["parameter_set_id"].tolist()]
    selections["created_at"] = datetime.now(timezone.utc)

    with connect_supabase() as supabase:
        with supabase.transaction():
            delete_existing_backtest_outputs(supabase, parameter_ids)
            insert_dataframe(
                supabase,
                "backtest_selection_event",
                selections,
                SELECTION_COLUMNS + ["created_at"],
            )

        id_map = fetch_selection_id_map(supabase, parameter_ids)

    if selections.empty:
        selections_with_ids = selections.copy()
    else:
        selections_with_ids = selections.merge(
            id_map,
            on=["parameter_set_id", "screen_type", "gvkey", "iid"],
            how="left",
            validate="one_to_one",
        )
        missing_ids = selections_with_ids["selection_event_id"].isna().sum()
        if missing_ids:
            raise RuntimeError(f"Missing selection_event_id values after insert: {missing_ids:,}")
        selections_with_ids["selection_event_id"] = selections_with_ids["selection_event_id"].astype("int64")

    price_flow = build_price_flow(con, selections_with_ids)
    price_flow["created_at"] = datetime.now(timezone.utc)

    with connect_supabase() as supabase:
        with supabase.transaction():
            insert_dataframe(
                supabase,
                "backtest_price_flow_3m",
                price_flow,
                PRICE_FLOW_COLUMNS + ["created_at"],
            )
            materialize_result_tables(supabase, parameter_names)

    print("\nS3/DuckDB backtest completed.")
    print(f"Selections loaded to Supabase: {len(selections):,}")
    print(f"Price-flow rows loaded to Supabase: {len(price_flow):,}")


if __name__ == "__main__":
    main()
