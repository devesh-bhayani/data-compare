"""Run the API with a fake S3 (moto), to try saving reports without an AWS account.

From the project folder:
    .venv/bin/python run_fake_s3.py
Then start the web page as usual (cd web && npm run dev). Every report is
"saved" to a bucket that lives only in this process's memory and disappears
when the server stops. Nothing is sent to AWS and nothing can be charged.
"""

import os
import warnings

BUCKET = "data-compare-demo-reports"


def main():
    warnings.filterwarnings("ignore", message="Boto3 will no longer support Python 3.9")
    # Fake keys replace any real ones in this process, so it cannot reach a real account.
    os.environ.update({
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
        "REPORTS_BUCKET": BUCKET,
    })
    from moto import mock_aws
    import boto3
    import uvicorn

    with mock_aws():
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        print(f"Fake S3 bucket {BUCKET!r} ready (in memory only).")
        uvicorn.run("api:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
