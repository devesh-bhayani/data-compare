"""Optional: save each report to a private S3 bucket and read it back by ID.

Off unless the REPORTS_BUCKET environment variable names a bucket. AWS keys
come from the usual places boto3 looks (environment variables, or the files
`aws configure` writes), never from this code or the repository.

The app needs only two permissions, on one prefix of one bucket:
s3:PutObject and s3:GetObject on <bucket>/reports/*. See docs/s3-policy.json.
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone

PREFIX = "reports/"

# Report IDs are made here, so anything else is refused before it reaches S3.
# That also stops an ID like "../secret" from naming a key outside reports/.
ID_PATTERN = re.compile(r"\d{8}T\d{6}Z-[0-9a-f]{8}")


class StorageError(Exception):
    """S3 could not be reached or refused the request (no keys, no bucket, no permission)."""


def new_report_id(now=None):
    """Sortable by time, with a random part so two reports in one second do not collide."""
    now = now or datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:8]}"


def object_key(report_id):
    return f"{PREFIX}{report_id}.json"


class ReportStore:
    def __init__(self, bucket, client=None):
        if client is None:
            import boto3   # imported here so the rest of the project never needs it
            client = boto3.client("s3")
        self.bucket = bucket
        self.client = client

    def save(self, payload):
        """Write one report as JSON, encrypted at rest. Returns its ID."""
        from botocore.exceptions import BotoCoreError, ClientError
        report_id = new_report_id()
        try:
            self.client.put_object(
                Bucket=self.bucket,
                Key=object_key(report_id),
                Body=json.dumps(payload, indent=2).encode("utf-8"),
                ContentType="application/json",
                ServerSideEncryption="AES256",
            )
        except (BotoCoreError, ClientError) as e:
            raise StorageError(describe(e)) from None
        return report_id

    def load(self, report_id):
        """Read a saved report back. KeyError if the ID is malformed or not there."""
        from botocore.exceptions import BotoCoreError, ClientError
        if not ID_PATTERN.fullmatch(report_id):
            raise KeyError(report_id)
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=object_key(report_id))
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("NoSuchKey", "404"):
                raise KeyError(report_id) from None
            if code == "AccessDenied":
                # Without s3:ListBucket, which this app deliberately does not
                # have, real S3 answers a missing key with 403, not 404.
                raise StorageError("AccessDenied: the report may not exist, since this app "
                                   "is not allowed to list the bucket, or the policy is wrong") from None
            raise StorageError(describe(e)) from None
        except BotoCoreError as e:
            raise StorageError(describe(e)) from None
        return json.loads(obj["Body"].read())


def describe(error):
    """A short reason for the user: the AWS error code if there is one, else the error's own text."""
    code = getattr(error, "response", {}).get("Error", {}).get("Code")
    return code or str(error)


def store_from_env():
    """A ReportStore for $REPORTS_BUCKET, or None when saving is not set up."""
    bucket = os.environ.get("REPORTS_BUCKET", "").strip()
    return ReportStore(bucket) if bucket else None
