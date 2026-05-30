import os
from dotenv import load_dotenv

load_dotenv()

S3_BUCKET = os.environ.get("S3_BUCKET", "nasdaq-stock-recommendation")
WRDS_USERNAME = os.environ["WRDS_USERNAME"]
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")

RAW_DAILY_PREFIX = "raw/compustat_daily_security"
RAW_ANNUAL_PREFIX = "raw/compustat_annual"
RAW_QUARTERLY_PREFIX = "raw/compustat_quarterly"

DAILY_MARKET_METRICS_PREFIX = "processed/daily_market_metrics"
RECENT_DAILY_VOLUME_METRICS_PREFIX = "processed/recent_daily_volume_metrics"
WEEKLY_MARKET_METRICS_PREFIX = "processed/weekly_market_metrics"

ANNUAL_GROWTH_HISTORY_PREFIX = "processed/annual_fundamental_growth_history"
QUARTERLY_GROWTH_HISTORY_PREFIX = "processed/quarterly_fundamental_growth_history"

SCREENING_RESULTS_PREFIX = "results/screening_results"
