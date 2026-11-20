import { useState } from 'react'
import { API_URL, compareFiles, fetchSample } from './api.js'
import Report from './Report.jsx'

function FilePicker({ label, file, onChange }) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <label className="file-pick">
        <input
          type="file"
          accept=".csv,text/csv"
          className="visually-hidden"
          aria-label={`${label} file`}
          onChange={(e) => onChange(e.target.files[0] ?? null)}
        />
        <span className="button secondary">Choose file</span>
        <span className="file-name">{file ? file.name : 'No file chosen'}</span>
      </label>
    </div>
  )
}

export default function App() {
  const [sourceFile, setSourceFile] = useState(null)
  const [targetFile, setTargetFile] = useState(null)
  const [key, setKey] = useState('student_id')
  const [status, setStatus] = useState('idle') // idle, loading, error or done
  const [error, setError] = useState(null)
  const [report, setReport] = useState(null)

  const busy = status === 'loading'
  const ready = sourceFile && targetFile && key.trim() && !busy

  // Moves the page through its states around one piece of async work:
  // loading while it runs, then done with a report, or error with a message.
  async function run(getReport) {
    setStatus('loading')
    setError(null)
    try {
      setReport(await getReport())
      setStatus('done')
    } catch (err) {
      setError(err.message)
      setStatus('error')
    }
  }

  function handleCompare(event) {
    event.preventDefault()
    run(() => compareFiles(sourceFile, targetFile, key.trim()))
  }

  function handleSample() {
    run(async () => {
      // Both downloads start at once; Promise.all waits until both have arrived.
      const [source, target] = await Promise.all([fetchSample('source.csv'), fetchSample('target.csv')])
      setSourceFile(source)
      setTargetFile(target)
      setKey('student_id')
      return compareFiles(source, target, 'student_id')
    })
  }

  return (
    <>
      <header className="app-bar">
        <h1>data-compare</h1>
        <p>Compare two CSV files on a key column and explain what differs.</p>
      </header>
      <main className="page">
        <form className="card" onSubmit={handleCompare}>
          <h2>Files</h2>
          <p className="muted">
            The source is the system of record; the target is the copy to check. Files go only to
            the API at {API_URL} and are deleted when the comparison ends.
          </p>
          <div className="form-grid">
            <FilePicker label="Source" file={sourceFile} onChange={setSourceFile} />
            <FilePicker label="Target" file={targetFile} onChange={setTargetFile} />
            <div className="field">
              <label className="field-label" htmlFor="key">Key column</label>
              <input
                id="key"
                type="text"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                spellCheck={false}
                autoComplete="off"
              />
            </div>
          </div>
          <div className="actions">
            <button type="submit" className="button" disabled={!ready}>
              {busy ? 'Comparing…' : 'Compare'}
            </button>
            <button type="button" className="button secondary" onClick={handleSample} disabled={busy}>
              Try the sample data
            </button>
          </div>
        </form>

        <div aria-live="polite">
          {busy && (
            <div className="notice">
              <p>Comparing the files and checking the counts in SQL…</p>
            </div>
          )}
          {status === 'error' && (
            <div className="alert-box" role="alert">
              <p>
                <strong>Could not compare.</strong> {error}
              </p>
            </div>
          )}
        </div>
        {status === 'done' && <Report report={report} />}

        <footer>A personal project with synthetic test data. Not affiliated with or endorsed by NYU.</footer>
      </main>
    </>
  )
}
