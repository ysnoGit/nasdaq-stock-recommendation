import os
from dotenv import load_dotenv

load_dotenv()


def require_env(name: str, setup_hint: str) -> str:
    value = os.environ.get(name)
    if value:
        return value

    raise RuntimeError(f"{name} is not set. Run:\n{setup_hint}")


S3_BUCKET = os.environ.get("S3_BUCKET", "nasdaq-stock-recommendation")
WRDS_USERNAME = os.environ.get("WRDS_USERNAME")
DEFAULT_AWS_REGION = "ap-northeast-2"
AWS_REGION = (
    os.environ.get("AWS_REGION")
    or os.environ.get("AWS_DEFAULT_REGION")
    or DEFAULT_AWS_REGION
)


def get_wrds_username() -> str:
    return require_env(
        "WRDS_USERNAME",
        'export WRDS_USERNAME="your_wrds_username"',
    )

RAW_DAILY_PREFIX = "raw/compustat_daily_security"
RAW_ANNUAL_PREFIX = "raw/compustat_annual"
RAW_QUARTERLY_PREFIX = "raw/compustat_quarterly"

DAILY_MARKET_METRICS_PREFIX = "processed/daily_market_metrics"
RECENT_DAILY_VOLUME_METRICS_PREFIX = "processed/recent_daily_volume_metrics"
WEEKLY_MARKET_METRICS_PREFIX = "processed/weekly_market_metrics"

ANNUAL_GROWTH_HISTORY_PREFIX = "processed/annual_fundamental_growth_history"
QUARTERLY_GROWTH_HISTORY_PREFIX = "processed/quarterly_fundamental_growth_history"

SCREENING_RESULTS_PREFIX = "results/screening_results"
