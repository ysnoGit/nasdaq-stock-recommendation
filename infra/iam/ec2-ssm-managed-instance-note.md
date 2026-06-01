# EC2 SSM Managed Instance Requirement

The EC2 instance role `NasdaqStockRecommendationEC2Role` must allow the instance
to register as an AWS Systems Manager managed instance.

Prefer attaching the AWS managed policy:

```text
AmazonSSMManagedInstanceCore
```

Without this policy, EventBridge Scheduler can start the EC2 instance, but the
later SSM Run Command schedule will not be able to run the batch script on the
instance.

After attaching the policy, verify SSM can see the instance:

```bash
aws ssm describe-instance-information --region ap-northeast-2
```
