"""Compare two CSV files on a key column and report what differs.

Step 3 of the build: rows only in one file, duplicate and blank keys, and
every cell whose raw text differs between matched rows. Later steps add
format-only vs real changes, a SQL cross-check and a plain-English report.

Usage:
    python3 compare.py data/source.csv data/target.csv --key student_id
"""

import argparse
import csv
from typing import Dict, List, NamedTuple, Set


class Table(NamedTuple):
    """One CSV file, indexed by its key column."""
    path: str
    columns: List[str]
    rows: Dict[str, Dict[str, str]]   # key -> row (the last copy, if a key repeats)
    row_count: int                    # every data row, including duplicates and blanks
    duplicate_keys: Set[str]
    blank_keys: int


def load(path, key):
    """Read a CSV into a dict from key to row, noting duplicate and blank keys."""
    rows, duplicates, blank, count = {}, set(), 0, 0
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
                k = (row[key] or "").strip()
                if not k:
                    blank += 1
                    continue
                if k in rows:
                    duplicates.add(k)
                rows[k] = row             # last copy wins, so duplicates are reported first
    except FileNotFoundError:
        raise SystemExit(f"File not found: {path}")
    return Table(path, columns, rows, count, duplicates, blank)


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
                changes.append({"key": k, "column": column,
                                "source": before, "target": after})

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
    }


def summary(table):
    return {"path": table.path, "rows": table.row_count,
            "duplicate_keys": sorted(table.duplicate_keys), "blank_keys": table.blank_keys}


def print_result(result, show=5):
    s, t = result["source"], result["target"]
    changed_rows = len({c["key"] for c in result["changes"]})
    print(f"Compared {s['path']} ({s['rows']:,} rows) with {t['path']} "
          f"({t['rows']:,} rows) on {result['key_column']}")
    print(f"  Only in source:   {len(result['only_in_source'])}")
    print(f"  Only in target:   {len(result['only_in_target'])}")
    print(f"  Duplicate keys:   source {len(s['duplicate_keys'])}, target {len(t['duplicate_keys'])}")
    print(f"  Blank keys:       source {s['blank_keys']}, target {t['blank_keys']}")
    print(f"  Matched keys:     {result['matched_keys']}")
    cells = len(result["changes"])
    print(f"  Changed rows:     {changed_rows} ({cells} cell{'' if cells == 1 else 's'})")
    for side in ("source", "target"):
        extra = result[f"columns_only_in_{side}"]
        if extra:
            print(f"  Columns only in {side}: {', '.join(extra)}")
    nothing_differs = not (result["only_in_source"] or result["only_in_target"]
                           or s["duplicate_keys"] or t["duplicate_keys"]
                           or s["blank_keys"] or t["blank_keys"] or result["changes"]
                           or result["columns_only_in_source"] or result["columns_only_in_target"])
    if nothing_differs:
        print("  No differences found.")
    for c in result["changes"][:show]:
        print(f"    {c['key']}  {c['column']}: {c['source']!r} -> {c['target']!r}")
    if len(result["changes"]) > show:
        print(f"    ... and {len(result['changes']) - show} more")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", help="the system of record (CSV)")
    parser.add_argument("target", help="the copy to check (CSV)")
    parser.add_argument("--key", required=True, help="column that identifies a row")
    parser.add_argument("--show", type=int, default=5, help="changed cells to print (default 5)")
    args = parser.parse_args()

    source = load(args.source, args.key)
    target = load(args.target, args.key)
    print_result(compare(source, target, args.key), show=args.show)


if __name__ == "__main__":
    main()
