from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parents[1]))

from server_pipeline.utils.wrds_connection import get_wrds_connection

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local convenience
    load_dotenv = None


PATTERNS = [
    "%s&p%500%",
    "%s&p 500%",
    "%s&p%",
    "%standard%poor%500%",
    "%standard%and%poor%500%",
    "%spx%",
]


def sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''").replace("%", "%%") + "'"


def table_exists(conn, table_name: str) -> bool:
    df = conn.raw_sql(
        f"""
        select 1
        from information_schema.tables
        where table_schema = 'comp'
          and table_name = {sql_literal(table_name)}
        limit 1
        """
    )
    return not df.empty


def get_columns(conn, table_name: str) -> pd.DataFrame:
    return conn.raw_sql(
        f"""
        select column_name, data_type
        from information_schema.columns
        where table_schema = 'comp'
          and table_name = {sql_literal(table_name)}
        order by ordinal_position
        """
    )


def discover_index_tables(conn) -> pd.DataFrame:
    tables = sorted(table for table in conn.list_tables(library="comp") if table.startswith("idx"))
    return pd.DataFrame({"table_name": tables})


def search_reference_table(conn, table_name: str, columns: pd.DataFrame) -> pd.DataFrame:
    column_names = columns["column_name"].tolist()
    id_columns = [
        name
        for name in ["gvkeyx", "newnum", "oldnum", "tic", "conm", "conml", "indextype"]
        if name in column_names
    ]
    text_columns = [
        row.column_name
        for row in columns.itertuples(index=False)
        if row.data_type in {"character varying", "character", "text"}
        and row.column_name not in {"gvkeyx"}
    ]
    if not id_columns or not text_columns:
        return pd.DataFrame()

    predicates = []
    for column in text_columns:
        for pattern in PATTERNS:
            predicates.append(f"lower(cast({column} as text)) like {sql_literal(pattern)}")
    selected_columns = list(dict.fromkeys(id_columns + text_columns))
    query = f"""
        select {", ".join(selected_columns)}
        from comp.{table_name}
        where {" or ".join(predicates)}
        limit 200
    """
    return conn.raw_sql(query)


def validate_daily_candidates(conn, candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty or "gvkeyx" not in candidates.columns:
        return pd.DataFrame()

    gvkeyx_values = (
        candidates["gvkeyx"]
        .dropna()
        .astype(str)
        .drop_duplicates()
        .sort_values()
        .tolist()
    )
    if not gvkeyx_values:
        return pd.DataFrame()

    values = ", ".join(sql_literal(value) for value in gvkeyx_values)
    return conn.raw_sql(
        f"""
        select
            gvkeyx,
            min(datadate) as first_date,
            max(datadate) as last_date,
            count(*) as row_count,
            count(prccd) as price_close_count,
            count(prccddiv) as total_return_count,
            count(prccddivn) as net_total_return_count
        from comp.idx_daily
        where gvkeyx in ({values})
        group by gvkeyx
        order by last_date desc, row_count desc, gvkeyx
        """,
        date_cols=["first_date", "last_date"],
    )


def find_exact_sp500_candidate(conn) -> pd.DataFrame:
    return conn.raw_sql(
        """
        select
            gvkeyx,
            tic,
            conm,
            indextype,
            idx13key,
            idxcstflg,
            idxstat,
            indexcat,
            indexgeo,
            indexid,
            indexval,
            spii,
            spmi,
            tici
        from comp.idx_index
        where gvkeyx = '000003'
           or lower(conm) = 's&p 500 comp-ltd'
           or lower(tic) = 'i0003'
        order by gvkeyx
        """
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Identify the Compustat Index Daily gvkeyx for the S&P 500."
    )
    parser.add_argument(
        "--broad-search",
        action="store_true",
        help="Also print broad S&P-like candidates from comp idx reference tables.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if load_dotenv is not None:
        load_dotenv()

    print("Connecting to WRDS using WRDS_USERNAME and ~/.pgpass...")
    conn = get_wrds_connection()
    try:
        if not table_exists(conn, "idx_daily"):
            raise RuntimeError("comp.idx_daily was not found in WRDS.")

        exact = find_exact_sp500_candidate(conn)
        if exact.empty:
            print("\nNo exact S&P 500 candidate was found by gvkeyx/ticker/name.")
        else:
            print("\nExact S&P 500 candidate from comp.idx_index:")
            print(exact.to_string(index=False))
            validation = validate_daily_candidates(conn, exact)
            if not validation.empty:
                print("\nCoverage in comp.idx_daily:")
                print(validation.to_string(index=False))

        if not args.broad_search:
            return

        print("\nWRDS comp tables beginning with idx:")
        tables = discover_index_tables(conn)
        print(tables.to_string(index=False))

        all_candidates = []
        for table_name in tables["table_name"].tolist():
            if table_name == "idx_daily":
                continue
            columns = get_columns(conn, table_name)
            matches = search_reference_table(conn, table_name, columns)
            if matches.empty:
                continue
            matches.insert(0, "source_table", table_name)
            all_candidates.append(matches)

        if not all_candidates:
            print("\nNo S&P-like candidates were found in comp idx reference tables.")
            print("Next step: inspect WRDS table names and columns manually.")
            return

        candidates = pd.concat(all_candidates, ignore_index=True, sort=False)
        print("\nS&P-like index reference candidates:")
        print(candidates.to_string(index=False))

        validation = validate_daily_candidates(conn, candidates)
        if not validation.empty:
            print("\nCandidate coverage in comp.idx_daily:")
            print(validation.to_string(index=False))

        if "gvkeyx" in candidates.columns:
            print("\nLikely next step:")
            print(
                "Choose the candidate whose description is S&P 500 / Standard & Poor's 500 "
                "and whose idx_daily coverage has recent prccd/prccddiv values."
            )
    finally:
        conn.close()
        print("\nWRDS connection closed.")


if __name__ == "__main__":
    main()
