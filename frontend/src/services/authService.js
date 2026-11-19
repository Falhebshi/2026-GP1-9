// Talks to the accounts server (backend/accounts/server.py), which Vite
// forwards from /api/auth (vite.config.js). The server keeps the session
// in an HttpOnly cookie: the browser sends it with every request and page
// scripts cannot read it, so nothing about the session is stored here.
//
// The user object is { id, name, email, role }, role "admin" or "engineer".

// Where each role lands after logging in (PBI 31)
export const HOME_BY_ROLE = {
  engineer: '/overview',
  admin: '/admin',
}

// The message shown when the server cannot be reached at all
const UNREACHABLE = 'The login service is not responding. Try again in a moment.'

// Sends a request and returns the parsed JSON (or null for an empty reply).
// Throws an Error whose message can be shown to the user as it is, with
// the HTTP status attached as error.status (0 if the server is unreachable).
async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`/api/auth${path}`, {
      credentials: 'same-origin',
      ...options,
      // Merged, so a caller's own headers keep the JSON content type
      headers: { 'Content-Type': 'application/json', ...options.headers },
    })
  } catch {
    const error = new Error(UNREACHABLE)
    error.status = 0
    throw error
  }

  const body = response.status === 204 ? null : await response.json().catch(() => null)

  if (!response.ok) {
    // The server's own messages (wrong password, deactivated, too many
    // attempts) are written to be shown as they are
    const detail = typeof body?.detail === 'string' ? body.detail : UNREACHABLE
    const error = new Error(detail)
    error.status = response.status
    throw error
  }

  return body
}

// Checks the email and password. Returns { user, isSample: false } or
// throws an Error to show on the Login page.
export async function logIn({ email, password }) {
  const { user } = await request('/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
  return { user, isSample: false }
}

// The message shown when logging out did not reach the server
const LOGOUT_FAILED = 'Could not log out: the login service is not responding. Try again.'

// Ends the session on the server, which also removes the cookie (PBI 32).
// The cookie is HttpOnly, so only the server can remove it: if the server
// cannot be reached, the session is still open and this throws, so the
// page can say so instead of pretending the user is logged out.
export async function logOut() {
  try {
    await request('/logout', { method: 'POST' })
  } catch (error) {
    // 401: the session had already ended, so the user is logged out
    if (error.status === 401) return
    throw new Error(LOGOUT_FAILED)
  }
}

// The logged-in user, or null when there is no valid session (never
// logged in, logged out, 30 minutes without activity, 8 hours passed,
// or the account was deactivated). Other errors are thrown.
export async function getCurrentUser() {
  try {
    const { user } = await request('/me')
    return user
  } catch (error) {
    if (error.status === 401) return null
    throw error
  }
}
