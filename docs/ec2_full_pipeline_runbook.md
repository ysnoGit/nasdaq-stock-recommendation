# EC2 Full Pipeline Runbook

This runbook is for the Amazon Linux EC2 instance that hosts:

```bash
~/projects/nasdaq-stock-recommendation
```

## One-Time EC2 Setup

Install system basics if they are not already present:

```bash
sudo dnf update -y
sudo dnf install -y git python3 python3-pip awscli
```

Clone or update the repository:

```bash
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/ysnoGit/nasdaq-stock-recommendation.git
cd nasdaq-stock-recommendation
```

Create the virtual environment if needed:

```bash
python3 -m venv venv
source venv/bin/activate
python3 -m pip install --upgrade pip
```

Install the project dependencies using the repository's dependency file if one exists.

## Activate The Virtual Environment

```bash
cd ~/projects/nasdaq-stock-recommendation
source venv/bin/activate
```

## Configure WRDS Username

Set the username for the current shell:

```bash
export WRDS_USERNAME="your_wrds_username"
```

Make it persistent:

```bash
echo 'export WRDS_USERNAME="your_wrds_username"' >> ~/.bashrc
source ~/.bashrc
```

Do not store the WRDS password in this repository.

## Configure AWS Region

The S3 bucket is in `ap-northeast-2`. Set both AWS region variables so boto3, AWS CLI, and DuckDB/httpfs agree:

```bash
export AWS_REGION="ap-northeast-2"
export AWS_DEFAULT_REGION="ap-northeast-2"
```

Make them persistent:

```bash
echo 'export AWS_REGION="ap-northeast-2"' >> ~/.bashrc
echo 'export AWS_DEFAULT_REGION="ap-northeast-2"' >> ~/.bashrc
source ~/.bashrc
```

## Configure ~/.pgpass

Expected format:

```text
wrds-pgdata.wharton.upenn.edu:9737:wrds:WRDS_USERNAME:WRDS_PASSWORD
```

Fix permissions:

```bash
chmod 600 ~/.pgpass
```

The pipeline checks that `~/.pgpass` exists and has safe permissions before opening a WRDS connection.

## Check The EC2 Environment

```bash
bash scripts/check_ec2_environment.sh
```

This checks Python, pip, venv state, required imports, `WRDS_USERNAME`, `~/.pgpass`, configured AWS region, bucket region, AWS identity, and S3 bucket access.

## Run The Full Pipeline

Preferred EC2 wrapper:

```bash
bash scripts/run_full_pipeline_ec2.sh
```

Direct Python runner:

```bash
python3 server_pipeline/run_full_pipeline.py
```

Useful runner options:

```bash
python3 server_pipeline/run_full_pipeline.py --skip-wrds
python3 server_pipeline/run_full_pipeline.py --only extraction
python3 server_pipeline/run_full_pipeline.py --only transform
```

The full pipeline now stops after processed feature creation. It no longer writes final screening result files by default. Load the processed features into Supabase after the full pipeline succeeds:

```bash
bash scripts/load_processed_features_to_supabase.sh --apply-schema
```

Weekly market metrics use `week_start_date` as the stable S3 partition key:

```text
s3://nasdaq-stock-recommendation/processed/weekly_market_metrics/year=YYYY/week_start_date=YYYY-MM-DD/weekly_market_metrics_YYYY-MM-DD.parquet
```

The file still includes `week_end_date`, `security_week_last_trade_date`, and `data_as_of_date` columns. Re-running the weekly step during the same trading week overwrites the same `week_start_date` partition and logs any old same-week `week_end_date` prefixes it deletes.

If legacy `week_end_date=...` folders still appear from earlier runs, remove them with:

```bash
python3 server_pipeline/daily/build_weekly_market_metrics_s3.py --cleanup-legacy-week-end
```

The cleanup command logs each exact S3 prefix before deleting it.

To rebuild a larger weekly history into the stable `week_start_date=...` layout, pass a start date. For example, `2025-10-10` belongs to `week_start_date=2025-10-06`:

```bash
python3 server_pipeline/daily/build_weekly_market_metrics_s3.py --start-week-date 2025-10-10
```

## Verify S3 Output

```bash
aws s3 ls s3://nasdaq-stock-recommendation/ --recursive --human-readable --summarize
```

Known raw fundamentals outputs:

```text
s3://nasdaq-stock-recommendation/raw/compustat_annual/latest/compustat_annual.parquet
s3://nasdaq-stock-recommendation/raw/compustat_quarterly/latest/compustat_quarterly.parquet
```

Raw fundamentals are kept as latest-only snapshots. Old versioned fundamentals folders such as `raw/compustat_annual/extract_date=...` and `raw/compustat_quarterly/extract_date=...` are cleaned by the fundamentals extraction step. To clean those old folders without running WRDS extraction:

```bash
python3 server_pipeline/fundamentals/extract_compustat_fundamentals_s3.py --cleanup-old-extracts-only
```

Known processed feature outputs:

```text
s3://nasdaq-stock-recommendation/processed/annual_fundamental_growth_history/annual_fundamental_growth_history.parquet
s3://nasdaq-stock-recommendation/processed/quarterly_fundamental_growth_history/quarterly_fundamental_growth_history.parquet
s3://nasdaq-stock-recommendation/processed/daily_market_metrics/
s3://nasdaq-stock-recommendation/processed/weekly_market_metrics/
s3://nasdaq-stock-recommendation/processed/recent_daily_volume_metrics/recent_daily_volume_metrics.parquet
```

## Troubleshooting

`WRDS_USERNAME` missing:

```bash
export WRDS_USERNAME="your_wrds_username"
```

Unsafe `.pgpass` permission:

```bash
chmod 600 ~/.pgpass
```

WRDS MFA or Duo issue:

Confirm the EC2 host is allowed by WRDS, complete any required WRDS login/MFA setup, then retry the extraction step.

AWS S3 `AccessDenied`:

```bash
aws sts get-caller-identity
aws s3 ls s3://nasdaq-stock-recommendation/
```

Confirm the EC2 role or configured AWS credentials can list and write to the bucket.

Python dependency errors:

```bash
cd ~/projects/nasdaq-stock-recommendation
source venv/bin/activate
python3 -m pip install --upgrade pip
```

Then install the missing package named by `scripts/check_ec2_environment.sh`.
