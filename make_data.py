"""Make a synthetic pair of student-enrollment extracts with planted problems.

source.csv is the "system of record". target.csv is the same data after a
make-believe load into a reporting system that went wrong in known ways.
planted.json is the answer key: every planted problem, so the tests can check
that compare.py finds exactly these and nothing else.

All data is synthetic. IDs look like S00001 and follow no real ID format.

Usage:
    python3 make_data.py                      # 1,000 rows, seed 42, writes data/
    python3 make_data.py --rows 5000 --seed 7 --drop-school Tandon
"""

import argparse
import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

COLUMNS = ["student_id", "first_name", "last_name", "school", "program",
           "term", "credits", "status", "enrolled_on"]

FIRST_NAMES = ["Aarav", "Maya", "Liam", "Sofia", "Noah", "Priya", "Ethan", "Zara",
               "Lucas", "Amara", "Kenji", "Elena", "Omar", "Chloe", "Ravi", "Hana",
               "Diego", "Nora", "Felix", "Leila"]
LAST_NAMES = ["Shah", "Garcia", "Kim", "Okafor", "Rossi", "Nguyen", "Patel", "Cohen",
              "Silva", "Novak", "Haddad", "Larsen", "Mehta", "Tanaka", "Brooks",
              "Moreau", "Ali", "Schmidt", "Reyes", "Iyer"]
PROGRAMS = {
    "Courant": ["MS Computer Science", "MS Mathematics"],
    "Tandon": ["MS Computer Engineering", "MS Cybersecurity"],
    "Stern": ["MBA", "MS Business Analytics"],
    "CAS": ["BA Economics", "BA Psychology"],
    "Steinhardt": ["MA Teaching", "MM Music Technology"],
}
SCHOOLS = list(PROGRAMS)
TERM = "Fall 2026"
FIRST_DAY = date(2026, 8, 24)

# How many rows get each problem. The row sets never overlap, so every
# problem in the answer key has exactly one cause.
N_DROPPED_FROM_SCHOOL = 12   # missing from the target, all from one school
N_DROPPED_ELSEWHERE = 3      # missing from the target, from other schools
N_EXTRA = 4                  # in the target only
N_BLANK_KEY = 1              # in the target with no student_id
N_DUPLICATES = 2             # rows copied twice into the target
N_CREDIT_CHANGES = 8         # real change: a different number of credits
N_STATUS_CHANGES = 4         # real change: enrolled <-> withdrawn
N_FORMAT_CHANGES = 25        # same value, written differently


def to_us_date(iso):
    """'2026-09-02' -> '09/02/2026'"""
    return date.fromisoformat(iso).strftime("%m/%d/%Y")


# Each format-only change: (column, kind, how to rewrite the value).
# A careful compare should treat all of these as the same value.
FORMAT_CHANGES = [
    ("school", "trailing space", lambda v: v + " "),
    ("last_name", "upper case", lambda v: v.upper()),
    ("credits", "decimal", lambda v: v + ".0"),
    ("enrolled_on", "date format", to_us_date),
    ("status", "title case", lambda v: v.title()),
]


def make_row(number, rng):
    school = rng.choice(SCHOOLS)
    return {
        "student_id": f"S{number:05d}",
        "first_name": rng.choice(FIRST_NAMES),
        "last_name": rng.choice(LAST_NAMES),
        "school": school,
        "program": rng.choice(PROGRAMS[school]),
        "term": TERM,
        "credits": str(rng.randint(3, 18)),
        "status": "enrolled" if rng.random() < 0.9 else "withdrawn",
        "enrolled_on": (FIRST_DAY + timedelta(days=rng.randint(0, 20))).isoformat(),
    }


def make_target(source, drop_school, rng):
    """Copy the source, damage the copy, and return (target rows, answer key)."""
    # Shuffle the row positions once, then hand out non-overlapping slices.
    positions = list(range(len(source)))
    rng.shuffle(positions)
    in_school = [i for i in positions if source[i]["school"] == drop_school]
    elsewhere = [i for i in positions if source[i]["school"] != drop_school]
    if len(in_school) < N_DROPPED_FROM_SCHOOL:
        raise SystemExit(f"Only {len(in_school)} {drop_school} rows: use more --rows.")

    dropped = in_school[:N_DROPPED_FROM_SCHOOL] + elsewhere[:N_DROPPED_ELSEWHERE]
    rest = in_school[N_DROPPED_FROM_SCHOOL:] + elsewhere[N_DROPPED_ELSEWHERE:]
    rng.shuffle(rest)
    needed = N_DUPLICATES + N_CREDIT_CHANGES + N_STATUS_CHANGES + N_FORMAT_CHANGES
    if len(rest) < needed:
        raise SystemExit(f"Need at least {needed} rows left after dropping: use more --rows.")

    cut1 = N_DUPLICATES
    cut2 = cut1 + N_CREDIT_CHANGES
    cut3 = cut2 + N_STATUS_CHANGES
    cut4 = cut3 + N_FORMAT_CHANGES
    duplicated, credit_rows, status_rows, format_rows = (
        rest[:cut1], rest[cut1:cut2], rest[cut2:cut3], rest[cut3:cut4])

    target = [dict(row) for row in source]   # copies, so the source stays clean
    real_changes, format_changes = [], []

    for i in credit_rows:
        old = target[i]["credits"]
        new = old
        while new == old:
            new = str(rng.randint(3, 18))
        target[i]["credits"] = new
        real_changes.append({"key": source[i]["student_id"], "column": "credits",
                             "source": old, "target": new})

    for i in status_rows:
        old = target[i]["status"]
        new = "withdrawn" if old == "enrolled" else "enrolled"
        target[i]["status"] = new
        real_changes.append({"key": source[i]["student_id"], "column": "status",
                             "source": old, "target": new})

    for n, i in enumerate(format_rows):
        column, kind, rewrite = FORMAT_CHANGES[n % len(FORMAT_CHANGES)]
        old = target[i][column]
        target[i][column] = rewrite(old)
        format_changes.append({"key": source[i]["student_id"], "column": column,
                               "kind": kind, "source": old, "target": target[i][column]})

    dropped_set = set(dropped)
    rows = [row for i, row in enumerate(target) if i not in dropped_set]
    rows += [dict(target[i]) for i in duplicated]          # second copies

    extras = [make_row(len(source) + k, rng) for k in range(1, N_EXTRA + 1)]
    rows += extras
    for k in range(N_BLANK_KEY):
        blank = make_row(len(source) + N_EXTRA + k + 1, rng)
        blank["student_id"] = ""
        rows.append(blank)

    rng.shuffle(rows)   # a real export rarely keeps the source's order

    def by_key(change):
        return (change["key"], change["column"])

    answer_key = {
        "key_column": "student_id",
        "source_rows": len(source),
        "target_rows": len(rows),
        "dropped_school": drop_school,
        "missing_from_target": sorted(source[i]["student_id"] for i in dropped),
        "missing_from_dropped_school": sorted(
            source[i]["student_id"] for i in dropped[:N_DROPPED_FROM_SCHOOL]),
        "extra_in_target": sorted(row["student_id"] for row in extras),
        "blank_key_rows": N_BLANK_KEY,
        "duplicate_keys": sorted(source[i]["student_id"] for i in duplicated),
        "real_changes": sorted(real_changes, key=by_key),
        "format_only_changes": sorted(format_changes, key=by_key),
    }
    return rows, answer_key


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--rows", type=int, default=1000, help="source rows (default 1000)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default 42)")
    parser.add_argument("--drop-school", default="Stern", choices=SCHOOLS,
                        help="school that loses most of the missing rows (default Stern)")
    parser.add_argument("--out", default="data", help="output folder (default data/)")
    args = parser.parse_args()

    rng = random.Random(args.seed)   # its own generator: same seed, same files
    source = [make_row(n, rng) for n in range(1, args.rows + 1)]
    target, answer_key = make_target(source, args.drop_school, rng)
    answer_key["seed"] = args.seed

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "source.csv", source)
    write_csv(out / "target.csv", target)
    (out / "planted.json").write_text(json.dumps(answer_key, indent=2) + "\n", encoding="utf-8")

    share = sum(row["school"] == args.drop_school for row in source) / len(source)
    print(f"Wrote {out}/source.csv ({len(source)} rows), {out}/target.csv "
          f"({len(target)} rows) and {out}/planted.json")
    print(f"Planted: {len(answer_key['missing_from_target'])} missing "
          f"({N_DROPPED_FROM_SCHOOL} from {args.drop_school}, which is {share:.0%} of the source), "
          f"{N_EXTRA} extra, {N_BLANK_KEY} blank key, {N_DUPLICATES} duplicated, "
          f"{len(answer_key['real_changes'])} real changes, "
          f"{len(answer_key['format_only_changes'])} format-only changes")


if __name__ == "__main__":
    main()
