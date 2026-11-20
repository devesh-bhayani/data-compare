"""Compare two CSV files on a key column and report what differs.

Rows only in one file, duplicate and blank keys, and every cell whose raw
text differs between matched rows, labelled as a real change or a
format-only change (same value, written differently). Later steps add a SQL
cross-check and a plain-English report.

Usage:
    python3 compare.py data/source.csv data/target.csv --key student_id
"""

import argparse
import csv
from collections import Counter
from datetime import datetime
from typing import Dict, List, NamedTuple, Set

# Date formats treated as the same date written differently. MM/DD/YYYY is
# assumed for slashes (US convention), so 09/11/2026 means September 11.
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y")


class Table(NamedTuple):
    """One CSV file, indexed by its key column."""
    path: str
    columns: List[str]
    rows: Dict[str, Dict[str, str]]   # key -> row (the last copy, if a key repeats)
    row_count: int                    # every data row, including duplicates and blanks
    duplicate_keys: Set[str]
    blank_keys: int
    malformed_rows: int               # rows with too few or too many fields


def load(path, key):
    """Read a CSV into a dict from key to row, noting duplicate, blank and malformed rows."""
    rows, duplicates, blank, malformed, count = {}, set(), 0, 0, 0
    try:
        # utf-8-sig also reads files Excel saved with a byte-order mark,
        # which would otherwise glue an invisible character onto the first header.
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames or []
            if key not in columns:
                raise SystemExit(f"Key column {key!r} is not in {path}. "
                                 f"Columns: {', '.join(columns) or '(none)'}")
            for row in reader:
                count += 1
                # DictReader fills missing fields with None and puts extra
                # fields under the key None. Count the row, then keep only
                # the named columns, with missing ones as empty text.
                if None in row or None in row.values():
                    malformed += 1
                row = {c: (row.get(c) or "") for c in columns}
                k = row[key].strip()
                if not k:
                    blank += 1
                    continue
                if k in rows:
                    duplicates.add(k)
                rows[k] = row             # last copy wins, so duplicates are reported first
    except FileNotFoundError:
        raise SystemExit(f"File not found: {path}")
    return Table(path, columns, rows, count, duplicates, blank, malformed)


def as_date(value):
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def as_number(value):
    try:
        return float(value)
    except ValueError:
        return None


def format_reason(before, after):
    """Why two different strings hold the same value, or None if they don't.

    Each rule is tried on top of the ones before it, so the reason names the
    first rule that makes the two values equal.
    """
    a, b = before.strip(), after.strip()
    if a == b:
        return "whitespace"
    a, b = a.lower(), b.lower()
    if a == b:
        return "letter case"
    date_a, date_b = as_date(a), as_date(b)
    if date_a is not None and date_a == date_b:
        return "date format"
    num_a, num_b = as_number(a), as_number(b)
    if num_a is not None and num_a == num_b:
        return "number format"
    return None


def compare(source, target, key):
    """Compare two loaded tables and return the differences as plain data."""
    source_keys, target_keys = set(source.rows), set(target.rows)
    matched = source_keys & target_keys

    # Only columns both files have can be compared cell by cell.
    shared = [c for c in source.columns if c in target.columns and c != key]

    changes = []
    for k in sorted(matched):
        for column in shared:
            before, after = source.rows[k][column], target.rows[k][column]
            if before != after:
                reason = format_reason(before, after)
                changes.append({"key": k, "column": column,
                                "source": before, "target": after,
                                "kind": "format only" if reason else "real change",
                                "reason": reason})

    return {
        "key_column": key,
        "source": summary(source),
        "target": summary(target),
        "only_in_source": sorted(source_keys - target_keys),
        "only_in_target": sorted(target_keys - source_keys),
        "matched_keys": len(matched),
        "columns_only_in_source": [c for c in source.columns if c not in target.columns],
        "columns_only_in_target": [c for c in target.columns if c not in source.columns],
        "changes": changes,
        "by_column": by_column(changes),
    }


def by_column(changes):
    """Per column: how many real changes, how many format-only, and why."""
    out = {}
    for c in changes:
        col = out.setdefault(c["column"], {"real": 0, "format_only": 0, "reasons": Counter()})
        if c["kind"] == "real change":
            col["real"] += 1
        else:
            col["format_only"] += 1
            col["reasons"][c["reason"]] += 1
    return {name: {"real": v["real"], "format_only": v["format_only"],
                   "reasons": dict(v["reasons"].most_common())}
            for name, v in sorted(out.items())}


def summary(table):
    return {"path": table.path, "rows": table.row_count,
            "duplicate_keys": sorted(table.duplicate_keys), "blank_keys": table.blank_keys,
            "malformed_rows": table.malformed_rows}


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def print_changes(title, changes, show):
    if not changes or show <= 0:
        return
    print(f"  {title} ({len(changes)}):")
    for c in changes[:show]:
        why = f"  [{c['reason']}]" if c["reason"] else ""
        print(f"    {c['key']}  {c['column']}: {c['source']!r} -> {c['target']!r}{why}")
    if len(changes) > show:
        print(f"    ... and {len(changes) - show} more")


def print_result(result, show=5):
    s, t = result["source"], result["target"]
    changes = result["changes"]
    real = [c for c in changes if c["kind"] == "real change"]
    fmt = [c for c in changes if c["kind"] == "format only"]
    changed_rows = len({c["key"] for c in changes})

    print(f"Compared {s['path']} ({s['rows']:,} rows) with {t['path']} "
          f"({t['rows']:,} rows) on {result['key_column']}")
    print(f"  Only in source:   {len(result['only_in_source'])}")
    print(f"  Only in target:   {len(result['only_in_target'])}")
    print(f"  Duplicate keys:   source {len(s['duplicate_keys'])}, target {len(t['duplicate_keys'])}")
    print(f"  Blank keys:       source {s['blank_keys']}, target {t['blank_keys']}")
    if s["malformed_rows"] or t["malformed_rows"]:
        print(f"  Malformed rows:   source {s['malformed_rows']}, target {t['malformed_rows']}")
    print(f"  Matched keys:     {result['matched_keys']}")
    print(f"  Changed rows:     {changed_rows} ({plural(len(changes), 'cell')}: "
          f"{len(real)} real, {len(fmt)} format only)")
    for side in ("source", "target"):
        extra = result[f"columns_only_in_{side}"]
        if extra:
            print(f"  Columns only in {side}: {', '.join(extra)}")

    nothing_differs = not (result["only_in_source"] or result["only_in_target"]
                           or s["duplicate_keys"] or t["duplicate_keys"]
                           or s["blank_keys"] or t["blank_keys"] or changes
                           or s["malformed_rows"] or t["malformed_rows"]
                           or result["columns_only_in_source"] or result["columns_only_in_target"])
    if nothing_differs:
        print("  No differences found.")
        return

    if result["by_column"]:
        width = max(len(name) for name in result["by_column"])
        print("  By column:")
        for name, col in result["by_column"].items():
            reasons = ", ".join(col["reasons"])
            note = f" ({reasons})" if reasons else ""
            print(f"    {name:<{width}}  {col['real']:>3} real, {col['format_only']:>3} format only{note}")

    print_changes("Real changes", real, show)
    print_changes("Format-only changes", fmt, show)


def print_sql_checks(checks):
    failed = [c for c in checks if not c["agree"]]
    if not failed:
        print(f"  SQL cross-check:  SQLite agrees on all {len(checks)} checks")
        return
    print(f"  SQL cross-check:  {len(failed)} of {len(checks)} checks DISAGREE")
    for c in failed:
        print(f"    {c['check']}: SQL {c['sql']}, Python {c['python']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="the system of record (CSV)")
    parser.add_argument("target", help="the copy to check (CSV)")
    parser.add_argument("--key", required=True, help="column that identifies a row")
    parser.add_argument("--show", type=int, default=5, help="changes of each kind to print (default 5)")
    parser.add_argument("--sql", action="store_true",
                        help="also answer the same questions in SQL (SQLite) and check both agree")
    args = parser.parse_args()

    source = load(args.source, args.key)
    target = load(args.target, args.key)
    result = compare(source, target, args.key)
    print_result(result, show=args.show)
    if args.sql:
        from sqlcheck import cross_check
        print_sql_checks(cross_check(args.source, args.target, args.key, result))


if __name__ == "__main__":
    main()
