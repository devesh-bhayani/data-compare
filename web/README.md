# data-compare web page

The React page for [data-compare](../README.md): pick two CSV files and a key column, then read the report the API sends back. Built with Vite and React. The styles come from `../styles/theme.css`, the same file the HTML report uses.

```bash
npm install
npm run dev     # http://localhost:5173 (the API must be running on port 8000)
npm run lint    # oxlint
npm run build   # production files in dist/
```

Needs Node 20.19 or later (22 was used). The page calls the API at `http://127.0.0.1:8000`; set `VITE_API_URL` to use another address.

| File | Job |
|---|---|
| `src/api.js` | The calls to the API, written with `fetch`, `async` and `await` |
| `src/App.jsx` | The form, the sample-data button, and the page's four states: idle, loading, error, done |
| `src/Report.jsx` | The report, in the same layout and CSS classes as `report.html` |
| `vite.config.js` | Pins the dev server to port 5173 (the origin the API allows) and lets it read `../styles` |
