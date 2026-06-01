# Daily EC2 Batch Automation

## Architecture

```text
EventBridge Scheduler
  -> starts EC2 instance
  -> systemd runs nasdaq-daily-batch.service on boot
  -> scripts/run_daily_batch_and_shutdown.sh runs the pipeline
  -> EC2 stops itself when AUTO_STOP_EC2=true
```

This keeps the instance off except during the daily batch window. The batch refreshes WRDS/S3 processed features, loads the Supabase serving tables, validates outputs, and then stops the instance after completion.

The active batch does not build `processed/recent_daily_volume_metrics/recent_daily_volume_metrics.parquet`. That file was part of the older S3-only screening design. Condition D is now calculated dynamically from at least three months of `security_feature_snapshot.volume_ratio` history in Supabase.

## Required EC2 Files

The secure environment file must already exist on EC2:

```text
/home/ec2-user/.nasdaq_pipeline.env
```

Required variables:

```text
WRDS_USERNAME
AWS_REGION
AWS_DEFAULT_REGION
SUPABASE_DB_URL
AUTO_STOP_EC2
```

Do not commit this file or print its contents.

WRDS password access uses:

```text
/home/ec2-user/.pgpass
```

Set safe permissions:

```bash
chmod 600 ~/.pgpass
```

## Batch Script

The batch entry point is:

```bash
scripts/run_daily_batch_and_shutdown.sh
```

It runs:

```bash
git pull origin main
python3 -m compileall server_pipeline
bash scripts/check_ec2_environment.sh
python3 server_pipeline/run_full_pipeline.py
bash scripts/load_processed_features_to_supabase.sh
```

It then prints Supabase row counts for:

```text
security_feature_snapshot
annual_growth_history
quarterly_growth_history
```

It also prints `security_feature_snapshot` date coverage, non-null `volume_ratio` rows, weekly matched rows, and dynamic Condition D lookback coverage.

It also verifies processed S3 output under:

```text
s3://nasdaq-stock-recommendation/processed/
```

Logs are written to:

```text
/home/ec2-user/projects/nasdaq-stock-recommendation/logs/daily_batch_YYYYMMDD_HHMMSS.log
```

## IAM Policies

Attach this policy to the EC2 instance role `NasdaqStockRecommendationEC2Role` so the instance can stop only itself:

```text
infra/iam/ec2-self-stop-policy.json
```

Example command:

```bash
aws iam put-role-policy \
  --role-name NasdaqStockRecommendationEC2Role \
  --policy-name NasdaqBatchSelfStopPolicy \
  --policy-document file://infra/iam/ec2-self-stop-policy.json
```

The EventBridge Scheduler setup uses:

```text
infra/iam/eventbridge-scheduler-trust-policy.json
infra/iam/eventbridge-start-ec2-policy.json
```

The start policy allows the scheduler role to start only:

```text
i-07311259548e90438
```

## Install The Systemd Service

On EC2:

```bash
cd /home/ec2-user/projects/nasdaq-stock-recommendation
bash scripts/install_daily_batch_systemd_service.sh
```

The service template is:

```text
infra/systemd/nasdaq-daily-batch.service
```

Manually start the service:

```bash
sudo systemctl start nasdaq-daily-batch.service
```

Check systemd logs:

```bash
journalctl -u nasdaq-daily-batch.service -n 100 --no-pager
```

Check batch logs:

```bash
ls -lh logs/
tail -100 logs/daily_batch_*.log
```

Disable the service:

```bash
sudo systemctl disable nasdaq-daily-batch.service
sudo systemctl daemon-reload
```

## Test Without Shutdown

Use the no-shutdown helper first:

```bash
cd /home/ec2-user/projects/nasdaq-stock-recommendation
bash scripts/test_daily_batch_no_shutdown.sh
```

This exports `AUTO_STOP_EC2=false` for the current process only. It does not modify:

```text
/home/ec2-user/.nasdaq_pipeline.env
```

## Create The EventBridge Schedule

Create or update the weekday 08:00 Asia/Seoul schedule:

```bash
cd /home/ec2-user/projects/nasdaq-stock-recommendation
bash scripts/create_eventbridge_start_ec2_schedule.sh
```

Run this command from AWS CloudShell or an AWS CLI profile with IAM and Scheduler administration permissions. The EC2 batch role normally should not be granted broad `iam:CreateRole` permissions just to bootstrap the scheduler.

If Scheduler reports that the execution role cannot be assumed, wait a minute and rerun the script. IAM trust-policy propagation can lag briefly after the role is created or updated. You can inspect the trust policy with:

```bash
aws iam get-role \
  --role-name NasdaqStartEC2SchedulerRole \
  --query 'Role.AssumeRolePolicyDocument' \
  --output json
```

It must include `scheduler.amazonaws.com` as the trusted service principal.

The schedule is:

```text
start-nasdaq-batch-ec2-weekdays
cron(0 8 ? * MON-FRI *)
Asia/Seoul
```

Verify it:

```bash
aws scheduler get-schedule \
  --name start-nasdaq-batch-ec2-weekdays \
  --region ap-northeast-2
```

## Manual Operations

Start EC2 manually:

```bash
aws ec2 start-instances \
  --instance-ids i-07311259548e90438 \
  --region ap-northeast-2
```

Stop EC2 manually:

```bash
aws ec2 stop-instances \
  --instance-ids i-07311259548e90438 \
  --region ap-northeast-2
```

Run the batch manually with normal shutdown behavior:

```bash
cd /home/ec2-user/projects/nasdaq-stock-recommendation
bash scripts/run_daily_batch_and_shutdown.sh
```

## Troubleshooting

### WRDS MFA/Duo Issue

If WRDS requires Duo approval, the unattended batch may fail. Do not add aggressive WRDS retry loops because repeated unapproved MFA attempts can lock Duo. Run the batch manually and approve the WRDS login if needed.

### Supabase Connection Issue

Confirm `SUPABASE_DB_URL` is set without printing it:

```bash
if [[ -n "${SUPABASE_DB_URL:-}" ]]; then echo "SUPABASE_DB_URL is set"; else echo "SUPABASE_DB_URL is missing"; fi
```

Then run:

```bash
bash scripts/check_ec2_environment.sh
```

### S3 Permission Issue

Check identity and bucket access:

```bash
aws sts get-caller-identity
aws s3 ls s3://nasdaq-stock-recommendation/ --region ap-northeast-2
```

### Systemd Service Failed

Inspect the service:

```bash
systemctl status nasdaq-daily-batch.service --no-pager
journalctl -u nasdaq-daily-batch.service -n 200 --no-pager
```

Then inspect the timestamped batch log under `logs/`.

### EC2 Did Not Stop

Confirm the env setting:

```bash
grep '^AUTO_STOP_EC2=' /home/ec2-user/.nasdaq_pipeline.env
```

Confirm the EC2 role has the self-stop policy from:

```text
infra/iam/ec2-self-stop-policy.json
```

### EventBridge Did Not Start EC2

Check the schedule:

```bash
aws scheduler get-schedule \
  --name start-nasdaq-batch-ec2-weekdays \
  --region ap-northeast-2
```

Confirm the scheduler role exists and has the inline start policy:

```bash
aws iam get-role --role-name NasdaqStartEC2SchedulerRole
aws iam get-role-policy \
  --role-name NasdaqStartEC2SchedulerRole \
  --policy-name StartNasdaqBatchEC2Policy
```
