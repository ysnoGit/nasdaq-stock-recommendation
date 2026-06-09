from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from pathlib import Path
import sys
import traceback

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[2]))

from backtest_lab.src.cleanup import cleanup_generated_outputs  # noqa: E402
from backtest_lab.src.config import (  # noqa: E402
    DEFAULT_END_DATE,
    DEFAULT_START_DATE,
    RESULT_DIR,
    ROOT,
    TMP_DIR,
    WARMUP_CALENDAR_DAYS,
)
from backtest_lab.src.db import (  # noqa: E402
    connect_supabase,
    execute_sql_file,
    replace_outcomes,
    upsert_parameter_grid,
)
from backtest_lab.src.parameter_grid import build_parameter_grid  # noqa: E402
from backtest_lab.src.price_outcome import calculate_price_outcomes  # noqa: E402
from backtest_lab.src.screening_logic import create_screening_connection, evaluate_parameter  # noqa: E402
from backtest_lab.src.storage import build_feature_parquets  # noqa: E402


def parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def start_run_log(conn, start_date: date, end_date: date, parameter_count: int) -> int:
    run_name = f"backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO backtest_run_log (
                run_name, start_date, end_date, parameter_set_count, status,
                local_output_path
            )
            VALUES (%s, %s, %s, %s, 'running', %s)
            RETURNING run_id
            """,
            (run_name, start_date, end_date, parameter_count, str(TMP_DIR)),
        )
        return int(cur.fetchone()[0])


def finish_run_log(conn, run_id: int, status: str, error_message: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE backtest_run_log
            SET status = %s, finished_at = now(), error_message = %s
            WHERE run_id = %s
            """,
            (status, error_message, run_id),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the isolated 192-combination backtest.")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--warmup-calendar-days", type=int, default=WARMUP_CALENDAR_DAYS)
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--parameter-set-id", type=int, help="Process one parameter set for debugging.")
    args = parser.parse_args()

    start_date = parse_date(args.start_date)
    end_date = parse_date(args.end_date) or date.today()
    if start_date is None:
        raise RuntimeError("A start date is required.")

    cleanup_generated_outputs()
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    grid = build_parameter_grid(args.start_date, args.end_date)
    with connect_supabase() as conn:
        if args.apply_schema:
            execute_sql_file(conn, ROOT / "sql" / "create_backtest_tables.sql")
        parameters = upsert_parameter_grid(conn, grid)
        if args.parameter_set_id:
            parameters = parameters[parameters["parameter_set_id"] == args.parameter_set_id].copy()
            if parameters.empty:
                raise RuntimeError(f"Unknown parameter_set_id: {args.parameter_set_id}")
        run_id = start_run_log(conn, start_date, end_date, len(parameters))

    try:
        build_feature_parquets(start_date, end_date, args.warmup_calendar_days)
        duck = create_screening_connection()
        total_outcomes = 0

        for progress, (_, row) in enumerate(parameters.iterrows(), start=1):
            parameter = row.to_dict()
            parameter_id = int(parameter["parameter_set_id"])
            name = parameter["parameter_set_name"]
            print(f"[{progress}/{len(parameters)}] parameter_set_id={parameter_id} {name}")

            selection_path = RESULT_DIR / f"selections_{parameter_id}.parquet"
            outcome_path = RESULT_DIR / f"outcomes_{parameter_id}.parquet"

            selections = evaluate_parameter(duck, parameter)
            selections.write_parquet(str(selection_path), compression="zstd")
            selection_count = int(selections.count("*").fetchone()[0])

            if selection_count:
                outcomes_relation = calculate_price_outcomes(
                    duck,
                    selection_path,
                    str(outcome_path),
                )
                outcomes_relation.write_parquet(str(outcome_path), compression="zstd")
                outcomes = outcomes_relation.df()
                for column in [
                    "selected_date", "latest_price_date", "high_price_date", "low_price_date"
                ]:
                    outcomes[column] = pd.to_datetime(outcomes[column]).dt.date
            else:
                outcomes = pd.DataFrame()

            with connect_supabase() as conn:
                with conn.transaction():
                    replace_outcomes(conn, parameter_id, outcomes)

            total_outcomes += len(outcomes)
            print(f"  earliest selections={selection_count:,}; compact outcomes={len(outcomes):,}")

        with connect_supabase() as conn:
            finish_run_log(conn, run_id, "succeeded")
        print(f"Backtest completed: parameters={len(parameters):,}, outcomes={total_outcomes:,}")
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        with connect_supabase() as conn:
            finish_run_log(conn, run_id, "failed", message[:4000])
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
