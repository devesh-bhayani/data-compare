"""Tests: the tool must find exactly the problems make_data.py planted.

Run from the project folder:
    python3 -m unittest -v
Standard library only, nothing to install.
"""

import filecmp
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from compare import compare, concentration_hints, format_reason, load
from report import summary_paragraphs, to_html, write_reports
from sqlcheck import cross_check

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
KEY = "student_id"


def run(source, target, key=KEY):
    s, t = load(str(source), key), load(str(target), key)
    return s, t, compare(s, t, key)


class AnswerKeyTests(unittest.TestCase):
    """On the seed-42 data, every finding must equal planted.json."""

    @classmethod
    def setUpClass(cls):
        cls.planted = json.loads((DATA / "planted.json").read_text(encoding="utf-8"))
        cls.source, cls.target, cls.result = run(DATA / "source.csv", DATA / "target.csv")

    def test_row_counts(self):
        self.assertEqual(self.result["source"]["rows"], self.planted["source_rows"])
        self.assertEqual(self.result["target"]["rows"], self.planted["target_rows"])

    def test_keys_on_one_side_only(self):
        self.assertEqual(self.result["only_in_source"], self.planted["missing_from_target"])
        self.assertEqual(self.result["only_in_target"], self.planted["extra_in_target"])

    def test_duplicate_and_blank_keys(self):
        self.assertEqual(self.result["target"]["duplicate_keys"], self.planted["duplicate_keys"])
        self.assertEqual(self.result["target"]["blank_keys"], self.planted["blank_key_rows"])
        self.assertEqual(self.result["source"]["duplicate_keys"], [])
        self.assertEqual(self.result["source"]["blank_keys"], 0)

    def test_real_changes(self):
        found = sorted((c["key"], c["column"], c["source"], c["target"])
                       for c in self.result["changes"] if c["kind"] == "real change")
        planted = sorted((c["key"], c["column"], c["source"], c["target"])
                         for c in self.planted["real_changes"])
        self.assertEqual(found, planted)

    def test_format_only_changes_and_reasons(self):
        reason_for = {"trailing space": "whitespace", "upper case": "letter case",
                      "title case": "letter case", "decimal": "number format",
                      "date format": "date format"}
        found = sorted((c["key"], c["column"], c["source"], c["target"], c["reason"])
                       for c in self.result["changes"] if c["kind"] == "format only")
        planted = sorted((c["key"], c["column"], c["source"], c["target"], reason_for[c["kind"]])
                         for c in self.planted["format_only_changes"])
        self.assertEqual(found, planted)

    def test_hint_names_the_dropped_school(self):
        hint = next(h for h in self.result["hints"] if h["type"] == "concentration")
        self.assertEqual((hint["column"], hint["value"]), ("school", self.planted["dropped_school"]))
        self.assertEqual((hint["count"], hint["of"]), (12, 15))

    def test_format_only_columns_hint(self):
        hint = next(h for h in self.result["hints"] if h["type"] == "format_only_columns")
        self.assertEqual(hint["columns"], ["enrolled_on", "last_name", "school"])

    def test_sql_agrees_with_python(self):
        checks = cross_check(str(DATA / "source.csv"), str(DATA / "target.csv"), KEY, self.result)
        self.assertTrue(all(c["agree"] for c in checks), [c for c in checks if not c["agree"]])

    def test_sql_catches_a_wrong_answer(self):
        """The cross-check is only useful if it notices when Python is wrong."""
        broken = dict(self.result, only_in_source=self.result["only_in_source"][1:])
        checks = cross_check(str(DATA / "source.csv"), str(DATA / "target.csv"), KEY, broken)
        self.assertIn("only in source", [c["check"] for c in checks if not c["agree"]])

    def test_summary_first_paragraph(self):
        first = summary_paragraphs(self.result)[0]
        self.assertEqual(first, "Compared 1,000 source rows with 992 target rows on `student_id`. "
                                "15 records are missing from the target, and 4 are in the target only. "
                                "2 keys appear more than once in the target. "
                                "1 row in the target has no key.")


class FormatReasonTests(unittest.TestCase):
    def test_cases(self):
        cases = [
            ("Stern", "Stern ", "whitespace"),
            ("Cohen", "COHEN", "letter case"),
            (" Stern", "STERN ", "letter case"),
            ("2026-09-11", "09/11/2026", "date format"),
            ("12", "12.0", "number format"),
            ("012", "12", "number format"),
            ("1.5", "1.50", "number format"),
            ("9", "16", None),
            ("enrolled", "withdrawn", None),
            ("2026-09-11", "2026-09-12", None),
            ("2026-09-11", "11/09/2026", None),   # slashes are read as MM/DD/YYYY
            ("", "0", None),
            ("Stern", "", None),
        ]
        for before, after, want in cases:
            with self.subTest(before=before, after=after):
                self.assertEqual(format_reason(before, after), want)


class HintThresholdTests(unittest.TestCase):
    """A hint needs 3+ rows, one value on 80%+ of them, and that value on at most 50% overall."""

    @staticmethod
    def rows(*schools):
        return [{"school": s} for s in schools]

    def hint(self, subset, population):
        return concentration_hints(subset, population, ["school"], "missing rows", "all rows", "Check {col}.")

    def setUp(self):
        self.population = self.rows(*(["Stern"] * 20 + ["CAS"] * 40 + ["Tandon"] * 40))

    def test_exactly_80_percent_counts(self):
        self.assertTrue(self.hint(self.rows("Stern", "Stern", "Stern", "Stern", "CAS"), self.population))

    def test_75_percent_does_not(self):
        self.assertFalse(self.hint(self.rows("Stern", "Stern", "Stern", "CAS"), self.population))

    def test_too_few_rows(self):
        self.assertFalse(self.hint(self.rows("Stern", "Stern"), self.population))

    def test_common_value_is_not_a_cause(self):
        common = self.rows(*(["CAS"] * 60 + ["Stern"] * 40))
        self.assertFalse(self.hint(self.rows("CAS", "CAS", "CAS"), common))


class EdgeCaseTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name)

    def tearDown(self):
        self.dir.cleanup()

    def csv(self, name, text, bom=False):
        p = self.path / name
        p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        return p

    def test_missing_key_column(self):
        p = self.csv("a.csv", "id,school\n1,Stern\n")
        with self.assertRaises(SystemExit) as e:
            load(str(p), KEY)
        self.assertIn("is not in", str(e.exception))

    def test_missing_file(self):
        with self.assertRaises(SystemExit) as e:
            load(str(self.path / "nope.csv"), KEY)
        self.assertIn("File not found", str(e.exception))

    def test_excel_byte_order_mark(self):
        a = self.csv("a.csv", "student_id,school\nS1,Stern\n", bom=True)
        b = self.csv("b.csv", "student_id,school\nS1,Stern\n")
        _, _, r = run(a, b)
        self.assertEqual((r["matched_keys"], r["changes"]), (1, []))

    def test_identical_files(self):
        _, _, r = run(DATA / "source.csv", DATA / "source.csv")
        self.assertEqual((r["only_in_source"], r["only_in_target"], r["changes"]), ([], [], []))
        self.assertIn("identical values", " ".join(summary_paragraphs(r)))

    def test_header_only_target(self):
        a = self.csv("a.csv", "student_id,school\nS1,Stern\nS2,CAS\n")
        b = self.csv("b.csv", "student_id,school\n")
        _, _, r = run(a, b)
        self.assertEqual((r["only_in_source"], r["target"]["rows"]), (["S1", "S2"], 0))

    def test_malformed_rows(self):
        a = self.csv("a.csv", "student_id,school\nS1,Stern\nS2,CAS\n")
        b = self.csv("b.csv", "student_id,school\nS1\nS2,CAS,extra\n")
        _, _, r = run(a, b)
        self.assertEqual(r["target"]["malformed_rows"], 2)

    def test_last_copy_of_a_duplicate_key_wins(self):
        a = self.csv("a.csv", "student_id,school\nS1,Stern\n")
        b = self.csv("b.csv", "student_id,school\nS1,CAS\nS1,Tandon\n")
        _, _, r = run(a, b)
        self.assertEqual(r["target"]["duplicate_keys"], ["S1"])
        self.assertEqual([c["target"] for c in r["changes"]], ["Tandon"])

    def test_sql_skips_blank_keys(self):
        """A blank key on one side only must not count as a key missing from the other."""
        with_blank = "student_id,school\nS1,Stern\n ,CAS\nS2,CAS\n"
        without = "student_id,school\nS1,Stern\nS3,CAS\n"
        for blank_side in ("source", "target"):
            with self.subTest(blank_in=blank_side):
                a = self.csv("a.csv", with_blank if blank_side == "source" else without)
                b = self.csv("b.csv", without if blank_side == "source" else with_blank)
                _, _, r = run(a, b)
                checks = cross_check(str(a), str(b), KEY, r)
                self.assertTrue(all(c["agree"] for c in checks), [c for c in checks if not c["agree"]])
                self.assertNotIn("", r["only_in_source"] + r["only_in_target"])

    def test_extra_column(self):
        a = self.csv("a.csv", "student_id,school\nS1,Stern\n")
        b = self.csv("b.csv", "student_id,school,email\nS1,Stern,x\n")
        _, _, r = run(a, b)
        self.assertEqual((r["columns_only_in_target"], r["changes"]), (["email"], []))


class ReportTests(unittest.TestCase):
    def test_html_escapes_values(self):
        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a.csv", Path(d) / "b.csv"
            a.write_text("student_id,note\nS1,hello\n", encoding="utf-8")
            b.write_text('student_id,note\nS1,"<script>alert(1)</script>"\n', encoding="utf-8")
            s, t, r = run(a, b)
            page = to_html(r, s, t, None, 10)
        self.assertNotIn("<script>", page)
        self.assertIn("&lt;script&gt;", page)

    def test_writes_three_files(self):
        s, t, r = run(DATA / "source.csv", DATA / "target.csv")
        with tempfile.TemporaryDirectory() as d:
            paths = write_reports(r, s, t, d)
            payload = json.loads(paths["json"].read_text(encoding="utf-8"))
            page = paths["html"].read_text(encoding="utf-8")
            markdown = paths["md"].read_text(encoding="utf-8")
        self.assertEqual(len(payload["summary"]), 4)
        self.assertEqual(page.count("<h1>"), 1)
        self.assertIn("**Likely cause:**", markdown)


class GeneratorTests(unittest.TestCase):
    def test_same_seed_same_files(self):
        """make_data.py with seed 42 must reproduce the committed data exactly."""
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, str(HERE / "make_data.py"), "--out", d],
                           check=True, capture_output=True)
            for name in ("source.csv", "target.csv", "planted.json"):
                with self.subTest(file=name):
                    self.assertTrue(filecmp.cmp(DATA / name, Path(d) / name, shallow=False))


if __name__ == "__main__":
    unittest.main()
