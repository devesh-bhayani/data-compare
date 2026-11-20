# Saving reports to a real S3 bucket

The API can save every report to a private S3 bucket and read it back by ID (`storage.py`). It is off unless `REPORTS_BUCKET` is set. To try it without an AWS account, run `.venv/bin/python run_fake_s3.py`: it starts the API with a fake S3 in memory (moto), so nothing is sent to AWS.

This page is for connecting a real bucket. The commands were checked against the AWS CLI reference on 2026-11-20 but **have not been run against a real account yet**.

## Before you start

- **Set a budget alert first.** In the AWS console, create a monthly cost budget (for example $1) with an email alert. AWS says monitoring budgets is free; budget *reports* cost $0.01 each, so do not schedule any.
- **Costs**: IAM is free. S3 charges for storage and requests, and these reports are a few kilobytes each. Check the S3 pricing page for your region before relying on that.
- **Python**: boto3 stopped supporting Python 3.9 on April 29, 2026. The tests run on 3.9 with the last boto3 release that supports it, but a real deployment should use Python 3.10 or later.
- The AWS CLI must be signed in as you (an account administrator) for the setup commands. The app itself gets a separate identity with far fewer rights.

## 1. The bucket

Bucket names are unique across all AWS accounts, so pick your own.

```bash
BUCKET=data-compare-reports-CHANGE-ME
aws s3api create-bucket --bucket "$BUCKET" --region us-east-1
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
```

AWS says new buckets do not allow public access by default; the second command makes that explicit. New objects are encrypted at rest (SSE-S3) by default since January 5, 2023, and `storage.py` also asks for it on every upload.

## 2. An identity for the app, with least privilege

`docs/s3-policy.json` allows exactly two actions, `s3:PutObject` and `s3:GetObject`, and only on `reports/*` in one bucket. The app cannot list, delete, or touch anything else. Fill in the bucket name in a copy outside the repository:

```bash
sed "s/YOUR-BUCKET-NAME/$BUCKET/" docs/s3-policy.json > ~/data-compare-s3-policy.json
aws iam create-user --user-name data-compare-app
aws iam put-user-policy --user-name data-compare-app --policy-name data-compare-reports --policy-document file://$HOME/data-compare-s3-policy.json
aws iam create-access-key --user-name data-compare-app
```

The last command prints the secret access key once, and only then. Keep both keys out of the repository: put them in the terminal that runs the API.

Use a new terminal, not one where `~/.data-compare-garage/env` was loaded: that file points boto3 at the local Garage server and switches encryption off.

```bash
export AWS_ACCESS_KEY_ID=...        # from create-access-key
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
REPORTS_BUCKET="$BUCKET" .venv/bin/uvicorn api:app
```

AWS recommends temporary credentials over long-term access keys wherever possible. An access key is acceptable for a local demo; on AWS compute (EC2, Lambda, ECS) the app should use an IAM role with the same policy instead, and no keys at all.

**One behavior to expect**: because the app may not list the bucket (no `s3:ListBucket`), S3 answers a request for a report that does not exist with 403 Access Denied, not 404. The API passes that on as a 502 that says the report may not exist. Granting `s3:ListBucket` would turn it into a clean 404, at the cost of letting the app see every report ID.

## 3. Cleaning up

Delete everything when the demo is over, in this order:

```bash
aws s3 rm "s3://$BUCKET" --recursive
aws s3api delete-bucket --bucket "$BUCKET"
aws iam delete-access-key --user-name data-compare-app --access-key-id THE-KEY-ID
aws iam delete-user-policy --user-name data-compare-app --policy-name data-compare-reports
aws iam delete-user --user-name data-compare-app
rm ~/data-compare-s3-policy.json
```

AWS refuses to delete a bucket that still holds objects, and a user that still has keys or policies, which is why the order matters.
