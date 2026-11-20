# data-compare

Compare two data sets on a key column and explain the differences in plain English: rows missing on either side, changed values, duplicate and blank keys, which changes are only formatting, and a likely cause.

A personal project with synthetic data, built in November 2026. **Work in progress.**

## Status

- [x] Synthetic test data with planted problems (`make_data.py`)
- [x] Report theme and a static mockup of the report (`styles/`)
- [x] Core compare (`compare.py`): rows only on one side, duplicate and blank keys, changed cells
- [x] Format-only vs real changes, with the reason and a per-column breakdown
- [x] The same comparison in SQL, as a cross-check (`sqlcheck.py`, `--sql`)
- [x] Plain-English report with a root-cause hint (`report.py`, `--report DIR`: Markdown, JSON and HTML)
- [x] Tests against the answer key (`test_compare.py`, 27 tests, `python3 -m unittest`)

## Compare

```bash
python3 compare.py data/source.csv data/target.csv --key student_id
```

On the default test data it prints (first lines):

```
Compared data/source.csv (1,000 rows) with data/target.csv (992 rows) on student_id
  Only in source:   15
  Only in target:   4
  Duplicate keys:   source 0, target 2
  Blank keys:       source 0, target 1
  Matched keys:     985
  Changed rows:     37 (37 cells: 12 real, 25 format only)
  By column:
    credits        8 real,   5 format only (number format)
    enrolled_on    0 real,   5 format only (date format)
    last_name      0 real,   5 format only (letter case)
    school         0 real,   5 format only (whitespace)
    status         4 real,   5 format only (letter case)
```

Every count, and the label on each of the 37 changed cells, matches `data/planted.json`.

### Design notes

- **Match by key, never by position.** A dict maps each key to its row, and set differences give the keys found on only one side.
- **Duplicate keys come first.** In a dict the last copy of a repeated key wins silently, so a comparison on a key that is not unique cannot be trusted until the duplicates are known.
- **Format-only vs real changes.** Two different strings can hold the same value: `'Tandon'` and `'Tandon '`, `'Cohen'` and `'COHEN'`, `'12'` and `'12.0'`, `'2026-09-11'` and `'09/11/2026'`. Each changed cell is tested against these rules in order (whitespace, letter case, date format, number format), and the first rule that makes the two equal is the reason. A column whose differences are all formatting points at a cleaning or type-conversion step rather than wrong data.
- **Dates with slashes are read as MM/DD/YYYY**, so `11/09/2026` against `2026-09-11` counts as a real change.
- **Messy files.** Files saved by Excel with a byte-order mark are read correctly. Rows with too few or too many fields are counted as malformed instead of crashing the run.

## Test data

```bash
python3 make_data.py            # 1,000 rows, seed 42, writes data/
python3 make_data.py --help     # other sizes, seeds, and which school loses rows
```

It writes three files:

| File | What it is |
|---|---|
| `data/source.csv` | The system of record: one row per student enrollment |
| `data/target.csv` | The same data after a make-believe load that went wrong in known ways, with rows shuffled |
| `data/planted.json` | The answer key: every planted problem, so the tests can check the tool finds exactly these |

Planted problems (default settings): 15 rows missing from the target (12 of them from one school), 4 extra rows, 1 row with a blank key, 2 duplicated keys, 12 real value changes (`credits` and `status`), and 25 format-only changes (trailing spaces, letter case, `12` written as `12.0`, dates written as MM/DD/YYYY).

All data is synthetic. Student IDs look like `S00001` and do not follow any real university's ID format. Names are drawn at random from two short lists.

Requires Python 3.9 or later, standard library only.

## Design

The HTML report and the web page share one stylesheet, `styles/theme.css`: Montserrat (falling back to Helvetica, then Arial) and a violet palette taken from NYU's public brand colors, since the sample data models a university. Body text is `#404040`, and every text and background pairing in the theme has a contrast ratio of 5:1 or better. `styles/preview.html` is a static mockup of the report, filled with values from the seed-42 data.

A personal project, not affiliated with or endorsed by NYU. It uses no NYU logo, seal or wordmark.
