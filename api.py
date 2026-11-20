"""HTTP API for data-compare: the same comparison as compare.py, behind FastAPI.

Run from the project folder, inside the virtual environment:
    uvicorn api:app --reload
Then open http://127.0.0.1:8000/docs to try every endpoint in the browser.
To also save each report to S3, set REPORTS_BUCKET first (see storage.py).

The comparison itself lives in compare.py, sqlcheck.py and report.py and is
not changed here. The command line and this API are two front doors to the
same functions, so they cannot disagree.
"""

import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from compare import InputError, compare, load
from report import build_payload
from sqlcheck import cross_check
from storage import StorageError, store_from_env

HERE = Path(__file__).resolve().parent

# The two test files the web page can load with one click. Only these names
# are served: the answer key (planted.json) and the code stay private.
SAMPLES = {name: HERE / "data" / name for name in ("source.csv", "target.csv")}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # per file
CHUNK_BYTES = 1024 * 1024

# Browsers block a page from reading answers from another origin (scheme, host
# and port) unless the server says it may. The React dev server runs on port
# 5173 and this API on 8000, so the page's origin has to be allowed here.
WEB_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

app = FastAPI(
    title="data-compare",
    version="0.2.0",
    description="Compare two CSV files on a key column and explain the differences in plain English.",
)
app.add_middleware(CORSMiddleware, allow_origins=WEB_ORIGINS, allow_methods=["GET", "POST"])

# Saving to S3 is optional: None unless REPORTS_BUCKET is set when the server starts.
STORE = store_from_env()


@app.get("/health")
def health():
    """A cheap check that the server is up."""
    return {"ok": True}


@app.get("/sample/{name}")
def sample(name: str):
    """One of the two synthetic test files, so the web page can demo without uploads."""
    path = SAMPLES.get(name)
    if path is None:
        raise HTTPException(404, f"No sample named {name!r}. Try source.csv or target.csv.")
    return FileResponse(path, media_type="text/csv", filename=name)


async def save_upload(upload, folder, label):
    """Copy one uploaded file into `folder`, refusing anything that is not a .csv or is too big.

    Returns (path on disk, the file name the user picked).
    """
    name = Path(upload.filename or "").name
    if not name.lower().endswith(".csv"):
        raise HTTPException(400, f"The {label} file must be a .csv file (got {name or 'no file name'!r}).")
    path = folder / f"{label}.csv"
    size = 0
    # By the time this runs the server has already received the upload, so the
    # limit protects the comparison (it loads both files into memory). A real
    # deployment would also cap the request size in front of the app.
    with path.open("wb") as out:
        while True:
            chunk = await upload.read(CHUNK_BYTES)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"The {label} file is larger than {MAX_UPLOAD_BYTES // 2**20} MB.")
            out.write(chunk)
    return path, name


def run_comparison(source_path, target_path, key, names):
    """The same three steps as `compare.py --report`, returning the report.json payload."""
    try:
        source = load(str(source_path), key)
        target = load(str(target_path), key)
    except InputError as e:
        # The message names the temporary file; the user knows the name they picked.
        message = str(e)
        for path, name in zip((source_path, target_path), names):
            message = message.replace(str(path), name)
        raise HTTPException(400, message) from None
    result = compare(source, target, key)
    checks = cross_check(str(source_path), str(target_path), key, result)
    payload = build_payload(result, source, target, checks)
    payload["source"]["path"], payload["target"]["path"] = names
    return payload


@app.post("/compare")
async def compare_files(
    source: Annotated[UploadFile, File(description="The system of record (CSV)")],
    target: Annotated[UploadFile, File(description="The copy to check (CSV)")],
    key: Annotated[str, Form(description="The column that identifies a row, for example student_id")],
):
    """Compare two uploaded CSV files and return the same JSON as report.json."""
    key = key.strip()
    if not key:
        raise HTTPException(400, "Give the name of the key column.")
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        source_path, source_name = await save_upload(source, folder, "source")
        target_path, target_name = await save_upload(target, folder, "target")
        # The comparison is ordinary blocking Python. Running it in a worker
        # thread keeps the server's event loop free to answer other requests
        # (such as /health) while a big comparison runs.
        payload = await run_in_threadpool(run_comparison, source_path, target_path, key,
                                          (source_name, target_name))
    if STORE is not None:
        # A failed save should not throw away a finished comparison, so the
        # report still comes back, with the reason it was not saved.
        try:
            payload["saved"] = await run_in_threadpool(STORE.save, payload)
        except StorageError as e:
            payload["saved"] = {"error": f"The report was not saved to S3 ({e})."}
    return payload


@app.get("/reports/{report_id}")
async def saved_report(report_id: str):
    """A report saved earlier by POST /compare, read back from S3."""
    if STORE is None:
        raise HTTPException(404, "Saving to S3 is not set up on this server (REPORTS_BUCKET is not set).")
    try:
        return await run_in_threadpool(STORE.load, report_id)
    except KeyError:
        raise HTTPException(404, f"No saved report with ID {report_id!r}.") from None
    except StorageError as e:
        raise HTTPException(502, f"S3 could not be read ({e}).") from None
