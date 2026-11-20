"""Turn a compare.py result into a plain-English summary and three report files.

report.md   readable on GitHub
report.json the full result, for code (POST /compare in api.py returns the same JSON)
report.html one self-contained page styled with styles/theme.css
"""

import html
import json
import re
from datetime import date
from pathlib import Path

from compare import natural_join, plural

THEME = Path(__file__).resolve().parent / "styles" / "theme.css"
REASON_WORDS = {"whitespace": "spaces", "letter case": "letter case",
                "number format": "number format", "date format": "date format"}


def summary_paragraphs(result, sql_checks=None):
    """The plain-English summary, as short paragraphs with `code` and **bold** marks."""
    s, t, key = result["source"], result["target"], result["key_column"]
    missing, extra = len(result["only_in_source"]), len(result["only_in_target"])
    paragraphs = []

    # 1. Rows and keys
    first = [f"Compared {s['rows']:,} source rows with {t['rows']:,} target rows on `{key}`."]
    if missing or extra:
        part_a = (f"{plural(missing, 'record')} {'is' if missing == 1 else 'are'} missing from the target"
                  if missing else "No records are missing from the target")
        part_b = f"{extra} {'is' if extra == 1 else 'are'} in the target only" if extra else "none are in the target only"
        first.append(f"{part_a}, and {part_b}.")
    else:
        first.append("Both files have exactly the same keys.")
    for side, info in (("target", t), ("source", s)):
        dups, blanks = len(info["duplicate_keys"]), info["blank_keys"]
        if dups:
            first.append(f"{plural(dups, 'key')} {'appears' if dups == 1 else 'appear'} "
                         f"more than once in the {side}.")
        if blanks:
            first.append(f"{plural(blanks, 'row')} in the {side} {'has' if blanks == 1 else 'have'} no key.")
        if info["malformed_rows"]:
            first.append(f"{plural(info['malformed_rows'], 'row')} in the {side} "
                         f"{'has' if info['malformed_rows'] == 1 else 'have'} too few or too many fields.")
    paragraphs.append(" ".join(first))

    # 2. Changed values
    changes = result["changes"]
    real_rows = {c["key"] for c in changes if c["kind"] == "real change"}
    format_rows = {c["key"] for c in changes} - real_rows
    if changes:
        reasons = [r for r in REASON_WORDS
                   if any(c["reason"] == r for c in changes if c["kind"] == "format only")]
        parts = []
        if format_rows:
            why = f" ({natural_join(REASON_WORDS[r] for r in reasons)})" if reasons else ""
            parts.append(f"{len(format_rows)} only in formatting{why}")
        if real_rows:
            per_col = [(c, v["real"]) for c, v in result["by_column"].items() if v["real"]]
            per_col.sort(key=lambda cv: -cv[1])
            cols = ", ".join(f"`{c}` {n}" for c, n in per_col)
            parts.append(f"{len(real_rows)} in real values ({cols})")
        n = len(real_rows | format_rows)
        paragraphs.append(f"{plural(n, 'matched record')} {'differs' if n == 1 else 'differ'}: "
                          f"{natural_join(parts)}.")
    elif result["matched_keys"]:
        paragraphs.append(f"All {result['matched_keys']:,} matched records have identical values.")

    # 3. Hints, strongest first: at most one per kind of finding
    seen = set()
    for hint in result.get("hints", []):
        kind = (hint["type"], hint.get("about"))
        if kind not in seen:
            seen.add(kind)
            paragraphs.append(hint["text"])

    # 4. SQL cross-check
    if sql_checks is not None:
        failed = [c for c in sql_checks if not c["agree"]]
        if failed:
            paragraphs.append(f"**The SQL cross-check disagrees on {len(failed)} of {len(sql_checks)} "
                              f"checks:** {natural_join(c['check'] for c in failed)}. "
                              f"Treat the counts above with caution.")
        else:
            paragraphs.append(f"A SQL cross-check in SQLite agrees on all {len(sql_checks)} checks.")
    return paragraphs


def inline_html(text):
    """Escape text, then turn **bold** and `code` marks into HTML."""
    out = html.escape(text, quote=False)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", out)


def plain(text):
    return text.replace("**", "").replace("`", "")


def display_columns(result, columns, key, limit=4):
    """Key first, then the column a hint points at, then the others, up to `limit`."""
    picked = [key]
    for hint in result.get("hints", []):
        if hint["type"] == "concentration" and hint["column"] in columns and hint["column"] not in picked:
            picked.append(hint["column"])
    for c in columns:
        if len(picked) >= limit:
            break
        if c not in picked:
            picked.append(c)
    return picked


# ---------- Markdown ----------

def md_value(value):
    """A cell value as a code span, quoted so trailing spaces stay visible."""
    text = repr(value).replace("|", "\\|")
    return f"`` {text} ``" if "`" in text else f"`{text}`"


def md_table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def to_markdown(result, source, target, sql_checks, limit):
    s, t, key = result["source"], result["target"], result["key_column"]
    real = [c for c in result["changes"] if c["kind"] == "real change"]
    fmt = [c for c in result["changes"] if c["kind"] == "format only"]
    out = ["# data-compare report", "",
           f"`{Path(s['path']).name}` vs `{Path(t['path']).name}`, key column `{key}`.", "",
           "## Summary", ""]
    for p in summary_paragraphs(result, sql_checks):
        out += [p, ""]

    out += ["## Counts", "", md_table(["", "Source", "Target"], [
        ["Rows", f"{s['rows']:,}", f"{t['rows']:,}"],
        ["Keys on this side only", len(result["only_in_source"]), len(result["only_in_target"])],
        ["Duplicate keys", len(s["duplicate_keys"]), len(t["duplicate_keys"])],
        ["Blank keys", s["blank_keys"], t["blank_keys"]],
        ["Malformed rows", s["malformed_rows"], t["malformed_rows"]],
    ]), "", f"Matched keys: {result['matched_keys']:,}.", ""]

    if result["by_column"]:
        out += ["## Changes by column", "", md_table(["Column", "Real", "Format only", "Reasons"], [
            [f"`{c}`", v["real"], v["format_only"], ", ".join(v["reasons"]) or ""]
            for c, v in result["by_column"].items()]), ""]

    for title, items, with_reason in (("Real changes", real, False), ("Format-only changes", fmt, True)):
        if items:
            out += [f"## {title} ({shown(len(items), limit)})", ""]
            header = [key, "column", "source", "target"] + (["reason"] if with_reason else [])
            rows = [[c["key"], f"`{c['column']}`", md_value(c["source"]), md_value(c["target"])]
                    + ([c["reason"]] if with_reason else []) for c in items[:limit]]
            out += [md_table(header, rows), ""]

    for title, keys, table in (("Missing from the target", result["only_in_source"], source),
                               ("Only in the target", result["only_in_target"], target)):
        if keys:
            cols = display_columns(result, table.columns, key)
            out += [f"## {title} ({shown(len(keys), limit)})", "",
                    md_table(cols, [[md_value(table.rows[k][c]) for c in cols] for k in keys[:limit]]), ""]

    if t["duplicate_keys"] or s["duplicate_keys"]:
        out += ["## Duplicate keys", ""]
        for side, info in (("source", s), ("target", t)):
            if info["duplicate_keys"]:
                out.append(f"- In the {side}: " + ", ".join(md_value(k) for k in info["duplicate_keys"]))
        out.append("")

    if sql_checks:
        out += ["## SQL cross-check", "", md_table(["Check", "SQL", "Python", "Agree"], [
            [c["check"], c["sql"], c["python"], "yes" if c["agree"] else "**NO**"] for c in sql_checks]), ""]

    out += ["---", f"Generated by data-compare on {date.today().isoformat()}."]
    return "\n".join(out) + "\n"


def shown(total, limit):
    return f"{total}" if total <= limit else f"first {limit} of {total}"


# ---------- HTML ----------

def h(value):
    return html.escape(str(value), quote=True)


def val(value):
    """A raw cell value in a dashed box, so trailing spaces show."""
    return f'<span class="val">{h(value)}</span>'


def html_table(header, rows):
    head = "".join(f"<th>{h(c)}</th>" for c in header)
    body = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return (f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead>'
            f"<tbody>{body}</tbody></table></div>")


def stat(value, label, alert=False):
    cls = "stat alert" if alert and value else "stat"
    return f'<div class="{cls}"><span class="value">{value:,}</span><span class="label">{h(label)}</span></div>'


def section(title, note, table):
    note_html = f'<p class="muted">{h(note)}</p>' if note else ""
    return f'<section class="card"><h2>{h(title)}</h2>{note_html}{table}</section>'


def to_html(result, source, target, sql_checks, limit):
    s, t, key = result["source"], result["target"], result["key_column"]
    real = [c for c in result["changes"] if c["kind"] == "real change"]
    fmt = [c for c in result["changes"] if c["kind"] == "format only"]
    try:
        theme = THEME.read_text(encoding="utf-8")
    except FileNotFoundError:
        theme = ""   # the report still works, just unstyled

    parts = []
    summary = "".join(f"<p>{inline_html(p)}</p>" for p in summary_paragraphs(result, sql_checks))
    parts.append(f'<section class="summary" aria-label="Summary">{summary}</section>')
    parts.append('<div class="stats">' + "".join([
        stat(s["rows"], "source rows"), stat(t["rows"], "target rows"),
        stat(len(result["only_in_source"]), "missing from target", alert=True),
        stat(len(result["only_in_target"]), "only in target"),
        stat(len(s["duplicate_keys"]) + len(t["duplicate_keys"]), "duplicate keys"),
        stat(s["blank_keys"] + t["blank_keys"], "blank keys"),
        stat(len(real), "real changes", alert=True), stat(len(fmt), "format only"),
    ]) + "</div>")

    changes = real[:limit] + fmt[:limit]
    if changes:
        rows = []
        for c in changes:
            badge = ('<span class="badge real">real change</span>' if c["kind"] == "real change"
                     else f'<span class="badge format">format only: {h(c["reason"])}</span>')
            rows.append([val(c["key"]), h(c["column"]), val(c["source"]), val(c["target"]), badge])
        note = (f"Showing {len(changes)} of {len(real) + len(fmt)}, real changes first. "
                "Dashed boxes mark where each raw value starts and ends, so a trailing space shows.")
        parts.append(section("Changed values", note,
                             html_table([key, "column", "source", "target", "type"], rows)))

    if result["by_column"]:
        rows = [[h(c), v["real"], v["format_only"], h(", ".join(v["reasons"]))]
                for c, v in result["by_column"].items()]
        parts.append(section("Changes by column", "", html_table(["column", "real", "format only", "reasons"], rows)))

    for title, keys, table, badge in (
            ("Missing from the target", result["only_in_source"], source, '<span class="badge missing">missing</span>'),
            ("Only in the target", result["only_in_target"], target, '<span class="badge extra">only in target</span>')):
        if keys:
            cols = display_columns(result, table.columns, key)
            rows = [[val(table.rows[k][c]) if c == key else h(table.rows[k][c]) for c in cols] + [badge]
                    for k in keys[:limit]]
            note = f"Showing {min(len(keys), limit)} of {len(keys)}. Values from the {'source' if table is source else 'target'}."
            parts.append(section(title, note, html_table(cols + [""], rows)))

    key_rows = []
    for side, info in (("source", s), ("target", t)):
        if info["duplicate_keys"]:
            key_rows.append([" ".join(val(k) for k in info["duplicate_keys"]),
                             f'<span class="badge key">appears more than once</span> in the {side}'])
        if info["blank_keys"]:
            key_rows.append([val(""), f'<span class="badge key">blank key</span> {plural(info["blank_keys"], "row")} in the {side}'])
        if info["malformed_rows"]:
            key_rows.append(["", f'<span class="badge key">malformed</span> {plural(info["malformed_rows"], "row")} in the {side}'])
    if key_rows:
        parts.append(section("Key problems", "", html_table([key, "problem"], key_rows)))

    if sql_checks:
        rows = [[h(c["check"]), c["sql"], c["python"],
                 '<span class="badge format">agrees</span>' if c["agree"] else '<span class="badge real">disagrees</span>']
                for c in sql_checks]
        parts.append(section("SQL cross-check", "The same questions answered again in SQLite, independently of the Python code.",
                             html_table(["check", "SQL", "Python", ""], rows)))

    title = f"{Path(s['path']).name} vs {Path(t['path']).name}"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>data-compare: {h(title)}</title>
<style>
{theme}
</style>
</head>
<body>
<header class="app-bar">
<h1>data-compare</h1>
<p>{h(title)}, key column {val(key)}</p>
</header>
<main class="page">
{"".join(parts)}
<footer>Generated by data-compare on {date.today().isoformat()}. Not affiliated with or endorsed by NYU.</footer>
</main>
</body>
</html>
"""


# ---------- JSON, and writing the files ----------

def sample_rows(result, table, keys, limit):
    """The first `limit` rows for these keys, with the columns the HTML report shows."""
    columns = display_columns(result, table.columns, result["key_column"])
    return {"columns": columns, "rows": [{c: table.rows[k][c] for c in columns} for k in keys[:limit]]}


def build_payload(result, source, target, sql_checks=None, limit=10):
    """The JSON both front doors return: report.json from the CLI, POST /compare from the API."""
    paragraphs = summary_paragraphs(result, sql_checks)
    return dict(result,
                summary=[plain(p) for p in paragraphs],
                summary_markdown=paragraphs,   # with the **bold** and `code` marks, for the web page
                samples={"only_in_source": sample_rows(result, source, result["only_in_source"], limit),
                         "only_in_target": sample_rows(result, target, result["only_in_target"], limit)},
                sql_checks=sql_checks)


def write_reports(result, source, target, out_dir, sql_checks=None, limit=10):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = build_payload(result, source, target, sql_checks, limit)
    paths = {
        "json": out / "report.json",
        "md": out / "report.md",
        "html": out / "report.html",
    }
    paths["json"].write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    paths["md"].write_text(to_markdown(result, source, target, sql_checks, limit), encoding="utf-8")
    paths["html"].write_text(to_html(result, source, target, sql_checks, limit), encoding="utf-8")
    return paths
