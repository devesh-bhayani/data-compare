"""Tests for the HTTP API in api.py.

They need the packages in requirements.txt:
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python -m unittest -v
Without those packages these tests are skipped and the core tests still run.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient
    import api
except ImportError:   # FastAPI or httpx is not installed
    api = None

from compare import compare, load
from report import build_payload
from sqlcheck import cross_check

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
KEY = "student_id"
WEB = "http://localhost:5173"


@unittest.skipIf(api is None, "FastAPI and httpx are not installed (see requirements.txt)")
class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(api.app)
        cls.source_bytes = (DATA / "source.csv").read_bytes()
        cls.target_bytes = (DATA / "target.csv").read_bytes()

    def post(self, source, target, key=KEY, names=("source.csv", "target.csv")):
        files = {"source": (names[0], source, "text/csv"), "target": (names[1], target, "text/csv")}
        return self.client.post("/compare", files=files, data={"key": key})

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual((r.status_code, r.json()), (200, {"ok": True}))

    def test_same_answer_as_the_command_line(self):
        """Two front doors, one answer: the API returns exactly what report.json holds."""
        r = self.post(self.source_bytes, self.target_bytes)
        self.assertEqual(r.status_code, 200)
        s, t = load(str(DATA / "source.csv"), KEY), load(str(DATA / "target.csv"), KEY)
        result = compare(s, t, KEY)
        expected = build_payload(result, s, t, cross_check(str(DATA / "source.csv"), str(DATA / "target.csv"), KEY, result))
        expected["source"]["path"], expected["target"]["path"] = "source.csv", "target.csv"
        self.assertEqual(r.json(), json.loads(json.dumps(expected)))
        self.assertIn("'Stern'", r.json()["summary"][2])

    def test_missing_key_column_names_the_uploaded_file(self):
        r = self.post(b"id,school\n1,Stern\n", b"id,school\n1,Stern\n", names=("mine.csv", "theirs.csv"))
        self.assertEqual(r.status_code, 400)
        detail = r.json()["detail"]
        self.assertIn("'student_id' is not in mine.csv", detail)
        self.assertNotIn(tempfile.gettempdir(), detail)

    def test_blank_key_name(self):
        r = self.post(self.source_bytes, self.target_bytes, key="   ")
        self.assertEqual(r.status_code, 400)

    def test_not_a_csv_file(self):
        r = self.post(self.source_bytes, self.target_bytes, names=("notes.txt", "target.csv"))
        self.assertEqual(r.status_code, 400)
        self.assertIn(".csv", r.json()["detail"])

    def test_not_utf8(self):
        latin1 = "student_id,school\nS1,Tandón\n".encode("latin-1")
        r = self.post(latin1, self.target_bytes)
        self.assertEqual(r.status_code, 400)
        self.assertIn("not UTF-8", r.json()["detail"])

    def test_upload_size_limit(self):
        with mock.patch.object(api, "MAX_UPLOAD_BYTES", 1000):
            r = self.post(self.source_bytes, self.target_bytes)
        self.assertEqual(r.status_code, 413)

    def test_cors_allows_only_the_web_page(self):
        def preflight(origin):
            return self.client.options("/compare", headers={
                "Origin": origin, "Access-Control-Request-Method": "POST"})
        self.assertEqual(preflight(WEB).headers.get("access-control-allow-origin"), WEB)
        self.assertNotIn("access-control-allow-origin", preflight("https://example.com").headers)

    def test_samples_but_not_the_answer_key(self):
        r = self.client.get("/sample/source.csv")
        self.assertEqual((r.status_code, r.content), (200, self.source_bytes))
        self.assertEqual(self.client.get("/sample/planted.json").status_code, 404)


if __name__ == "__main__":
    unittest.main()
