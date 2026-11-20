"""The same comparison in SQL, as an independent cross-check.

Both CSVs are loaded into an in-memory SQLite database exactly as written:
every column as text, duplicate rows and blank keys included. The questions
compare.py answers in Python are then answered again in SQL. If the two
implementations disagree on a count, one of them has a bug.

SQL compares text exactly, so it cannot tell '12' from '12.0' apart as the
same number. Its changed-cell counts therefore match compare.py's raw counts
(real plus format-only), not its real-change counts.
"""

import csv
import sqlite3

# {k} is the quoted key column, {c} a quoted data column.
QUERIES = {
    "only_in_source": """
        SELECT DISTINCT TRIM(s.{k}) FROM source s
        LEFT JOIN target t ON TRIM(t.{k}) = TRIM(s.{k})
        WHERE t.{k} IS NULL AND TRIM(s.{k}) <> ''
        ORDER BY 1""",
    "only_in_target": """
        SELECT DISTINCT TRIM(t.{k}) FROM target t
        LEFT JOIN source s ON TRIM(s.{k}) = TRIM(t.{k})
        WHERE s.{k} IS NULL AND TRIM(t.{k}) <> ''
        ORDER BY 1""",
    "duplicate_keys": """
        SELECT TRIM({k}) FROM {table}
        WHERE TRIM({k}) <> ''
        GROUP BY TRIM({k}) HAVING COUNT(*) > 1
        ORDER BY 1""",
    "blank_keys": """
        SELECT COUNT(*) FROM {table} WHERE TRIM({k}) = ''""",
    # IS NOT is SQLite's null-safe "not equal": NULL IS NOT NULL is false.
    "changed_cells": """
        SELECT COUNT(DISTINCT TRIM(s.{k})) FROM source s
        JOIN target t ON TRIM(s.{k}) = TRIM(t.{k})
        WHERE TRIM(s.{k}) <> '' AND s.{c} IS NOT t.{c}""",
}


def quote(name):
    """Quote a column name for SQL, so headers with spaces or quotes still work."""
    return '"' + name.replace('"', '""') + '"'


def load_table(con, table, path):
    """Load a CSV into a SQLite table of text columns and return its header."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, [])
        width = len(header)
        # Short rows are padded and long rows cut, the same way compare.py treats them.
        rows = [(row + [""] * width)[:width] for row in reader]
    columns = ", ".join(f"{quote(c)} TEXT" for c in header)
    con.execute(f"CREATE TABLE {table} ({columns})")
    con.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * width)})", rows)
    return header


def run_sql(source_path, target_path, key):
    """Answer the comparison questions in SQL and return the answers."""
    con = sqlite3.connect(":memory:")
    try:
        source_columns = load_table(con, "source", source_path)
        target_columns = load_table(con, "target", target_path)
        k = quote(key)

        def column(sql):
            return [row[0] for row in con.execute(sql)]

        def number(sql):
            return con.execute(sql).fetchone()[0]

        shared = [c for c in source_columns if c in target_columns and c != key]
        return {
            "only_in_source": column(QUERIES["only_in_source"].format(k=k)),
            "only_in_target": column(QUERIES["only_in_target"].format(k=k)),
            "source_duplicate_keys": column(QUERIES["duplicate_keys"].format(k=k, table="source")),
            "target_duplicate_keys": column(QUERIES["duplicate_keys"].format(k=k, table="target")),
            "source_blank_keys": number(QUERIES["blank_keys"].format(k=k, table="source")),
            "target_blank_keys": number(QUERIES["blank_keys"].format(k=k, table="target")),
            "changed_cells": {c: number(QUERIES["changed_cells"].format(k=k, c=quote(c)))
                              for c in shared},
        }
    finally:
        con.close()


def cross_check(source_path, target_path, key, result):
    """Compare the SQL answers with compare.py's result. Returns a list of checks."""
    sql = run_sql(source_path, target_path, key)
    python_changed = {c: v["real"] + v["format_only"] for c, v in result["by_column"].items()}

    checks = [
        ("only in source", len(sql["only_in_source"]), len(result["only_in_source"]),
         sql["only_in_source"] == result["only_in_source"]),
        ("only in target", len(sql["only_in_target"]), len(result["only_in_target"]),
         sql["only_in_target"] == result["only_in_target"]),
        ("duplicate keys in source", len(sql["source_duplicate_keys"]),
         len(result["source"]["duplicate_keys"]),
         sql["source_duplicate_keys"] == result["source"]["duplicate_keys"]),
        ("duplicate keys in target", len(sql["target_duplicate_keys"]),
         len(result["target"]["duplicate_keys"]),
         sql["target_duplicate_keys"] == result["target"]["duplicate_keys"]),
        ("blank keys in source", sql["source_blank_keys"], result["source"]["blank_keys"], None),
        ("blank keys in target", sql["target_blank_keys"], result["target"]["blank_keys"], None),
    ]
    for c, n in sql["changed_cells"].items():
        checks.append((f"changed cells in {c}", n, python_changed.get(c, 0), None))

    # A check with no list to compare passes when the two counts are equal.
    return [{"check": name, "sql": s, "python": p, "agree": (s == p) if same is None else same}
            for name, s, p, same in checks]
