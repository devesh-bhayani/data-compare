"""Tests for saving reports to S3 (storage.py and the API's use of it).

They run against moto, a fake S3 inside the test process: no AWS account,
no network, nothing to pay for. They need the packages in requirements.txt
and are skipped without them. The policy test needs nothing.

LiveServerTests run only when asked, against whatever server the environment
names (Garage from garage.sh, or a real bucket):
    . ~/.data-compare-garage/env && DATA_COMPARE_LIVE_S3=1 .venv/bin/python -m unittest test_storage
They leave a few small reports in the bucket, since the app has no delete permission.
"""

import json
import os
import unittest
import warnings
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from moto import mock_aws
    import api
    from storage import ReportStore, StorageError, new_report_id, store_from_env
except ImportError:   # boto3, moto or FastAPI is not installed
    mock_aws = None



def setUpModule():
    # boto3 warns that it is dropping Python 3.9; the tests are not about that.
    # (Set here, not at import: unittest resets warning filters when the run starts.)
    warnings.filterwarnings("ignore", message="Boto3 will no longer support Python 3.9")


HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
BUCKET = "data-compare-test-reports"
FAKE_AWS = {"AWS_ACCESS_KEY_ID": "testing", "AWS_SECRET_ACCESS_KEY": "testing",
            "AWS_SESSION_TOKEN": "testing", "AWS_DEFAULT_REGION": "us-east-1"}


class PolicyTests(unittest.TestCase):
    """docs/s3-policy.json must stay least-privilege: two actions, one prefix."""

    def test_policy_allows_only_reading_and_writing_reports(self):
        policy = json.loads((HERE / "docs" / "s3-policy.json").read_text(encoding="utf-8"))
        [statement] = policy["Statement"]
        self.assertEqual(statement["Effect"], "Allow")
        self.assertEqual(sorted(statement["Action"]), ["s3:GetObject", "s3:PutObject"])
        self.assertTrue(statement["Resource"].endswith("/reports/*"), statement["Resource"])
        self.assertNotIn("*", statement["Resource"].split(":::")[1].split("/")[0])


@unittest.skipIf(mock_aws is None, "boto3, moto and FastAPI are not installed (see requirements.txt)")
class FakeS3Case(unittest.TestCase):
    """Every test gets fake AWS keys and a fresh fake S3 with one empty bucket."""

    def setUp(self):
        env = mock.patch.dict(os.environ, FAKE_AWS)   # never real keys, even if some are set
        env.start()
        self.addCleanup(env.stop)
        # Nor a real server: moto only answers requests addressed to AWS.
        for name in ("AWS_ENDPOINT_URL", "AWS_ENDPOINT_URL_S3", "REPORTS_SSE"):
            os.environ.pop(name, None)
        aws = mock_aws()
        aws.start()
        self.addCleanup(aws.stop)
        self.store = ReportStore(BUCKET)
        self.store.client.create_bucket(Bucket=BUCKET)


class StorageTests(FakeS3Case):
    def test_round_trip(self):
        saved = self.store.save({"summary": ["hello"]})
        self.assertEqual(self.store.load(saved["id"]), {"summary": ["hello"]})

    def test_saved_under_reports_as_encrypted_json(self):
        saved = self.store.save({"a": 1})
        self.assertEqual(saved["key"], f"reports/{saved['id']}.json")
        head = self.store.client.head_object(Bucket=BUCKET, Key=saved["key"])
        self.assertEqual(head["ContentType"], "application/json")
        self.assertEqual(head["ServerSideEncryption"], "AES256")
        self.assertTrue(saved["encrypted"])

    def test_encryption_is_believed_only_when_the_server_confirms_it(self):
        """Garage accepts the encryption header and stores the report in plain text."""
        real_put = self.store.client.put_object
        def ignores_header(**kwargs):
            reply = real_put(**kwargs)
            reply.pop("ServerSideEncryption", None)
            return reply
        with mock.patch.object(self.store.client, "put_object", side_effect=ignores_header):
            saved = self.store.save({"a": 1})
        self.assertFalse(saved["encrypted"])

    def test_encryption_can_be_switched_off_for_servers_without_it(self):
        saved = ReportStore(BUCKET, encrypt=False).save({"a": 1})
        head = self.store.client.head_object(Bucket=BUCKET, Key=saved["key"])
        self.assertNotIn("ServerSideEncryption", head)
        self.assertFalse(saved["encrypted"])
        for value, expected in (("none", False), ("NONE", False), ("", True), ("AES256", True), ("off", True)):
            with self.subTest(REPORTS_SSE=value), \
                    mock.patch.dict(os.environ, {"REPORTS_BUCKET": BUCKET, "REPORTS_SSE": value}):
                self.assertIs(store_from_env().encrypt, expected)

    def test_ids_sort_by_time_and_do_not_collide(self):
        when = datetime(2026, 11, 20, 16, 5, 9, tzinfo=timezone.utc)
        self.assertTrue(new_report_id(when).startswith("20261120T160509Z-"))
        self.assertNotEqual(new_report_id(when), new_report_id(when))

    def test_bad_ids_never_reach_s3(self):
        client = mock.Mock()
        store = ReportStore(BUCKET, client=client)
        for bad in ("../secret", "", "20261120T160509Z-ABCDEF12", "20261120T160509Z-abcdef12.json"):
            with self.subTest(report_id=bad), self.assertRaises(KeyError):
                store.load(bad)
        client.get_object.assert_not_called()

    def test_unknown_id(self):
        with self.assertRaises(KeyError):
            self.store.load(new_report_id())

    def test_access_denied_explains_the_missing_list_permission(self):
        """Real S3 says AccessDenied, not NoSuchKey, for a missing key when the caller cannot list."""
        from botocore.exceptions import ClientError
        client = mock.Mock()
        client.get_object.side_effect = ClientError({"Error": {"Code": "AccessDenied"}}, "GetObject")
        with self.assertRaises(StorageError) as e:
            ReportStore(BUCKET, client=client).load(new_report_id())
        self.assertIn("may not exist", str(e.exception))

    def test_missing_bucket_is_a_storage_error(self):
        with self.assertRaises(StorageError) as e:
            ReportStore("no-such-bucket-data-compare").save({})
        self.assertIn("NoSuchBucket", str(e.exception))

    def test_off_unless_the_bucket_is_named(self):
        with mock.patch.dict(os.environ, {"REPORTS_BUCKET": ""}):
            self.assertIsNone(store_from_env())
        with mock.patch.dict(os.environ, {"REPORTS_BUCKET": BUCKET}):
            self.assertEqual(store_from_env().bucket, BUCKET)


class ApiStorageTests(FakeS3Case):
    def setUp(self):
        super().setUp()
        self.client = TestClient(api.app)

    def compare(self):
        files = {"source": ("source.csv", (DATA / "source.csv").read_bytes(), "text/csv"),
                 "target": ("target.csv", (DATA / "target.csv").read_bytes(), "text/csv")}
        return self.client.post("/compare", files=files, data={"key": "student_id"})

    def test_compare_saves_and_the_report_reads_back(self):
        with mock.patch.object(api, "STORE", self.store):
            r = self.compare()
            saved = r.json()["saved"]
            back = self.client.get(f"/reports/{saved['id']}")
        self.assertEqual(saved["key"], f"reports/{saved['id']}.json")
        self.assertTrue(saved["encrypted"])
        self.assertEqual(back.status_code, 200)
        expected = {k: v for k, v in r.json().items() if k != "saved"}
        self.assertEqual(back.json(), expected)

    def test_failed_save_still_returns_the_report(self):
        with mock.patch.object(api, "STORE", ReportStore("no-such-bucket-data-compare")):
            r = self.compare()
        self.assertEqual(r.status_code, 200)
        self.assertIn("NoSuchBucket", r.json()["saved"]["error"])
        self.assertIn("Stern", r.json()["summary"][2])

    def test_unknown_report_id(self):
        with mock.patch.object(api, "STORE", self.store):
            r = self.client.get(f"/reports/{new_report_id()}")
        self.assertEqual(r.status_code, 404)

    def test_saving_switched_off(self):
        with mock.patch.object(api, "STORE", None):
            r = self.compare()
            back = self.client.get(f"/reports/{new_report_id()}")
        self.assertNotIn("saved", r.json())
        self.assertEqual(back.status_code, 404)
        self.assertIn("not set up", back.json()["detail"])


@unittest.skipUnless(os.environ.get("DATA_COMPARE_LIVE_S3") and mock_aws is not None,
                     "set DATA_COMPARE_LIVE_S3=1 to test against a running S3 server")
class LiveServerTests(unittest.TestCase):
    """The same checks against a real server, configured only by the environment."""

    def setUp(self):
        self.store = store_from_env()
        self.assertIsNotNone(self.store, "REPORTS_BUCKET is not set")

    def test_round_trip(self):
        saved = self.store.save({"summary": ["live"]})
        self.assertEqual(self.store.load(saved["id"]), {"summary": ["live"]})

    def test_encryption_flag_matches_what_the_server_stored(self):
        saved = self.store.save({"a": 1})
        head = self.store.client.head_object(Bucket=self.store.bucket, Key=saved["key"])
        self.assertEqual(saved["encrypted"], head.get("ServerSideEncryption") == "AES256")

    def test_unknown_id(self):
        # 404 on a server that lets the app list the bucket; on AWS with the
        # least-privilege policy, the 403 explained in storage.py.
        try:
            self.store.load(new_report_id())
        except KeyError:
            pass
        except StorageError as e:
            self.assertIn("may not exist", str(e))
        else:
            self.fail("an unknown ID was found")


if __name__ == "__main__":
    unittest.main()
