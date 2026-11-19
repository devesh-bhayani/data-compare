# data-compare

Compare two data sets on a key column and explain the differences in plain English: rows missing on either side, changed values, duplicate and blank keys, which changes are only formatting, and a likely cause.

A personal project with synthetic data, built in November 2026. **Work in progress.**

## Status

- [x] Synthetic test data with planted problems (`make_data.py`)
- [ ] Core compare (`compare.py`)
- [ ] Format-only vs real changes
- [ ] The same comparison in SQL, as a cross-check
- [ ] Plain-English report with a root-cause hint
- [ ] Tests against the answer key

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
