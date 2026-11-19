// Talks to the accounts server's administrator endpoints
// (backend/accounts/server.py), which Vite forwards from /api/admin
// (vite.config.js). Only a logged-in administrator gets answers; the
// session cookie is sent by the browser.
//
// An engineer is { id, name, email, status, created_at }, status "active"
// or "inactive", created_at an ISO time in UTC.

const UNREACHABLE = 'The accounts service is not responding. Try again in a moment.'

// The server's answer for an action on an account that was deleted
// meanwhile (or an administrator's id). Only this 404 means "gone"; any
// other 404 (e.g. a server still running older code without this action)
// is an ordinary failure.
const ACCOUNT_GONE = 'This account no longer exists.'
const NOT_AVAILABLE =
  "The accounts service can't do this yet. If it was just updated, restart it and try again."

// Sends a request and returns the parsed JSON. Throws an Error whose message
// can be shown as it is; error.field names the form field it belongs to
// ("name", "email" or "password"), when there is one; error.gone is true
// when the account no longer exists; and error.status is the HTTP status
// (0 if the server is unreachable).
async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`/api/admin${path}`, {
      credentials: 'same-origin',
      ...options,
      headers: { 'Content-Type': 'application/json', ...options.headers },
    })
  } catch {
    const error = new Error(UNREACHABLE)
    error.status = 0
    throw error
  }

  const body = await response.json().catch(() => null)

  if (!response.ok) {
    const detail = body?.detail
    const gone = response.status === 404 && detail === ACCOUNT_GONE
    let message = typeof detail === 'string' ? detail : (detail?.message ?? UNREACHABLE)
    // A 404 that is not about the account: the server has no such action
    if (response.status === 404 && !gone) message = NOT_AVAILABLE
    const error = new Error(message)
    error.status = response.status
    error.gone = gone
    error.field = typeof detail === 'object' ? detail?.field : undefined
    throw error
  }

  return body
}

// Every engineer account, ordered by name (ADM-02)
export async function listEngineers() {
  const { engineers } = await request('/engineers')
  return engineers
}

// Creates an engineer account and returns it (ADM-01). The password is
// checked by the server with the same rules as every account.
export async function createEngineer({ name, email, password }) {
  return request('/engineers', {
    method: 'POST',
    body: JSON.stringify({ name, email, password }),
  })
}

// Makes an engineer account "active" or "inactive" and returns it (ADM-03).
// Deactivating logs the engineer out at once. An account that no longer
// exists answers with error.status 404.
export async function setStatus(id, status) {
  return request(`/engineers/${encodeURIComponent(id)}/status`, {
    method: 'POST',
    body: JSON.stringify({ status }),
  })
}

// A random five-word passphrase for the Generate button
export async function generatePassphrase() {
  const { passphrase } = await request('/passphrase')
  return passphrase
}
