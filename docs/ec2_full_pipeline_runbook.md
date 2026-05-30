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

This checks Python, pip, venv state, required imports, `WRDS_USERNAME`, `~/.pgpass`, AWS identity, and S3 bucket access.

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
python3 server_pipeline/run_full_pipeline.py --only screening
```

The screening group currently contains a TODO placeholder because the existing screening implementation is still under `scripts/build_final_screening_results.py` and is not yet an S3-ready `server_pipeline` step.

## Verify S3 Output

```bash
aws s3 ls s3://nasdaq-stock-recommendation/ --recursive --human-readable --summarize
```

Known raw fundamentals outputs:

```text
s3://nasdaq-stock-recommendation/raw/compustat_annual/latest/compustat_annual.parquet
s3://nasdaq-stock-recommendation/raw/compustat_quarterly/latest/compustat_quarterly.parquet
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
