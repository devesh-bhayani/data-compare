// Talks to the FastAPI server in ../api.py.
//
// Every function here is async, so it returns a promise straight away. The
// browser runs the page on one thread; while a request is out, that thread is
// free to repaint and handle clicks. Each `await` is a point where the
// function pauses until the server answers, then carries on from that line.

export const API_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

// FastAPI sends errors as {"detail": ...}: a sentence for the API's own 400
// and 413 answers, a list of problems when it could not read the request (422).
async function errorMessage(res) {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return body.detail.map((d) => d.msg).join('; ')
  } catch {
    // The body was not JSON; fall back to the status line.
  }
  return `The server answered ${res.status} ${res.statusText}.`
}

async function request(path, options) {
  let res
  try {
    res = await fetch(API_URL + path, options)
  } catch {
    // fetch rejects only when no answer arrived at all: the server is down,
    // the address is wrong, or the browser blocked the answer (CORS).
    throw new Error(`Could not reach the API at ${API_URL}. Is it running? (uvicorn api:app)`)
  }
  // An HTTP error such as 400 still resolves, so it has to be checked here.
  if (!res.ok) throw new Error(await errorMessage(res))
  return res
}

export async function fetchSample(name) {
  const res = await request(`/sample/${name}`)
  const blob = await res.blob()
  return new File([blob], name, { type: 'text/csv' })
}

export async function compareFiles(source, target, key) {
  const form = new FormData()
  form.append('source', source)
  form.append('target', target)
  form.append('key', key)
  const res = await request('/compare', { method: 'POST', body: form })
  return res.json()
}
