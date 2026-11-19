// Talks to the accounts server's administrator endpoints
// (backend/accounts/server.py), which Vite forwards from /api/admin
// (vite.config.js). Only a logged-in administrator gets answers; the
// session cookie is sent by the browser.
//
// An engineer is { id, name, email, status, created_at }, status "active"
// or "inactive", created_at an ISO time in UTC.

const UNREACHABLE = 'The accounts service is not responding. Try again in a moment.'

// Sends a request and returns the parsed JSON. Throws an Error whose message
// can be shown as it is; error.field names the form field it belongs to
// ("name", "email" or "password"), when there is one, and error.status is
// the HTTP status (0 if the server is unreachable).
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
    const error = new Error(
      typeof detail === 'string' ? detail : (detail?.message ?? UNREACHABLE),
    )
    error.status = response.status
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

// A random five-word passphrase for the Generate button
export async function generatePassphrase() {
  const { passphrase } = await request('/passphrase')
  return passphrase
}
