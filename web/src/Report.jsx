// Shows one POST /compare answer (the same JSON as report.json) in the same
// layout and classes as report.html, so the page and the file look alike.
//
// React escapes every string it renders, so a cell holding "<script>" shows
// as text. The Python report has to call html.escape for the same safety.

const LIMIT = 10

// Turns the summary's **bold** and `code` marks into elements.
function Marked({ text }) {
  return text.split(/(\*\*.+?\*\*|`.+?`)/).map((part, i) => {
    if (part.length > 4 && part.startsWith('**') && part.endsWith('**')) {
      return <strong key={i}>{part.slice(2, -2)}</strong>
    }
    if (part.length > 2 && part.startsWith('`') && part.endsWith('`')) {
      return <code key={i}>{part.slice(1, -1)}</code>
    }
    return part
  })
}

// A raw cell value in a dashed box, so a trailing space shows.
function Val({ value }) {
  return <span className="val">{value}</span>
}

function Badge({ kind, children }) {
  return <span className={`badge ${kind}`}>{children}</span>
}

function Stat({ value, label, alert = false }) {
  return (
    <div className={alert && value ? 'stat alert' : 'stat'}>
      <span className="value">{value.toLocaleString('en-US')}</span>
      <span className="label">{label}</span>
    </div>
  )
}

function Section({ title, note, children }) {
  return (
    <section className="card">
      <h2>{title}</h2>
      {note && <p className="muted">{note}</p>}
      {children}
    </section>
  )
}

function Table({ header, rows }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>{header.map((h, i) => <th key={i}>{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r}>{row.map((cell, c) => <td key={c}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function plural(n, word) {
  return `${n} ${word}${n === 1 ? '' : 's'}`
}

function downloadJson(report) {
  const blob = new Blob([JSON.stringify(report, null, 2) + '\n'], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'report.json'
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

function RowSample({ title, keys, sample, side, badge }) {
  if (keys.length === 0) return null
  const rows = sample.rows.map((row) => [
    ...sample.columns.map((c, i) => (i === 0 ? <Val key={c} value={row[c]} /> : row[c])),
    badge,
  ])
  return (
    <Section title={title} note={`Showing ${sample.rows.length} of ${keys.length}. Values from the ${side}.`}>
      <Table header={[...sample.columns, '']} rows={rows} />
    </Section>
  )
}

export default function Report({ report }) {
  const { source, target, key_column: key } = report
  const real = report.changes.filter((c) => c.kind === 'real change')
  const format = report.changes.filter((c) => c.kind === 'format only')
  const changes = [...real.slice(0, LIMIT), ...format.slice(0, LIMIT)]

  const keyProblems = []
  for (const [side, info] of [['source', source], ['target', target]]) {
    if (info.duplicate_keys.length) {
      keyProblems.push([
        info.duplicate_keys.map((k) => <Val key={k} value={k} />),
        <>
          <Badge kind="key">appears more than once</Badge> in the {side}
        </>,
      ])
    }
    if (info.blank_keys) {
      keyProblems.push([
        <Val key="blank" value="" />,
        <>
          <Badge kind="key">blank key</Badge> {plural(info.blank_keys, 'row')} in the {side}
        </>,
      ])
    }
    if (info.malformed_rows) {
      keyProblems.push([
        '',
        <>
          <Badge kind="key">malformed</Badge> {plural(info.malformed_rows, 'row')} in the {side}
        </>,
      ])
    }
  }

  return (
    <>
      <div className="report-head">
        <h2>
          {source.path} vs {target.path}, key column <Val value={key} />
        </h2>
        <button type="button" className="button secondary" onClick={() => downloadJson(report)}>
          Download report.json
        </button>
      </div>

      <section className="summary" aria-label="Summary">
        {report.summary_markdown.map((p, i) => (
          <p key={i}>
            <Marked text={p} />
          </p>
        ))}
      </section>

      <div className="stats">
        <Stat value={source.rows} label="source rows" />
        <Stat value={target.rows} label="target rows" />
        <Stat value={report.only_in_source.length} label="missing from target" alert />
        <Stat value={report.only_in_target.length} label="only in target" />
        <Stat value={source.duplicate_keys.length + target.duplicate_keys.length} label="duplicate keys" />
        <Stat value={source.blank_keys + target.blank_keys} label="blank keys" />
        <Stat value={real.length} label="real changes" alert />
        <Stat value={format.length} label="format only" />
      </div>

      {changes.length > 0 && (
        <Section
          title="Changed values"
          note={`Showing ${changes.length} of ${report.changes.length}, real changes first. Dashed boxes mark where each raw value starts and ends, so a trailing space shows.`}
        >
          <Table
            header={[key, 'column', 'source', 'target', 'type']}
            rows={changes.map((c) => [
              <Val key="key" value={c.key} />,
              c.column,
              <Val key="source" value={c.source} />,
              <Val key="target" value={c.target} />,
              c.kind === 'real change' ? (
                <Badge kind="real">real change</Badge>
              ) : (
                <Badge kind="format">format only: {c.reason}</Badge>
              ),
            ])}
          />
        </Section>
      )}

      {Object.keys(report.by_column).length > 0 && (
        <Section title="Changes by column">
          <Table
            header={['column', 'real', 'format only', 'reasons']}
            rows={Object.entries(report.by_column).map(([column, v]) => [
              column,
              v.real,
              v.format_only,
              Object.keys(v.reasons).join(', '), // reasons maps each reason to its count
            ])}
          />
        </Section>
      )}

      <RowSample
        title="Missing from the target"
        keys={report.only_in_source}
        sample={report.samples.only_in_source}
        side="source"
        badge={<Badge kind="missing">missing</Badge>}
      />
      <RowSample
        title="Only in the target"
        keys={report.only_in_target}
        sample={report.samples.only_in_target}
        side="target"
        badge={<Badge kind="extra">only in target</Badge>}
      />

      {keyProblems.length > 0 && (
        <Section title="Key problems">
          <Table header={[key, 'problem']} rows={keyProblems} />
        </Section>
      )}

      {report.sql_checks && (
        <Section
          title="SQL cross-check"
          note="The same questions answered again in SQLite, independently of the Python code."
        >
          <Table
            header={['check', 'SQL', 'Python', '']}
            rows={report.sql_checks.map((c) => [
              c.check,
              c.sql,
              c.python,
              c.agree ? <Badge kind="format">agrees</Badge> : <Badge kind="real">disagrees</Badge>,
            ])}
          />
        </Section>
      )}
    </>
  )
}
