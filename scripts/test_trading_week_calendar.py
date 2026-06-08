from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[1]))

from server_pipeline.utils.trading_calendar import official_week_end_trading_date  # noqa: E402


def main() -> None:
    normal_week = official_week_end_trading_date(date(2026, 6, 1))
    assert normal_week == date(2026, 6, 5), normal_week

    friday_holiday_week = official_week_end_trading_date(date(2026, 7, 1))
    assert friday_holiday_week == date(2026, 7, 2), friday_holiday_week

    thursday_data_date = date(2026, 6, 4)
    thursday_week_end = official_week_end_trading_date(thursday_data_date)
    assert thursday_week_end == date(2026, 6, 5), thursday_week_end
    assert thursday_data_date != thursday_week_end

    print("Trading week calendar checks passed.")


if __name__ == "__main__":
    main()
