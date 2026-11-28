import { useEffect, useRef, useState } from 'react'
import { Navigate, Outlet, useLocation } from 'react-router-dom'
import EmptyState from './EmptyState'
import { HOME_BY_ROLE, getCurrentUser } from '../services/authService'

// Lets a page open only for a logged-in user with the given role.
//
//   role   "engineer" (the traffic pages) or "admin" (the Admin Dashboard)
//
// It asks the accounts server who is logged in every time the page address
// changes, so a session that ended (logout, 30 minutes without activity,
// 8 hours, or a deactivated account) is noticed on the next click:
//   nobody logged in       -> the Login page
//   the other role         -> that role's own first page
//   the right role         -> the page, with { user } for useOutletContext()
//
// Working on one page also counts as activity: while the user clicks,
// types, scrolls or drags, it tells the server "still here" at most once
// every 5 minutes. Someone who walks away sends nothing, so the server
// ends the session 30 to 35 minutes after their last interaction.

// The shortest time between two "still here" requests
const KEEP_ALIVE_MS = 5 * 60 * 1000

// What counts as interaction (scrolling a page or a chart is "wheel")
const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart']

function RequireRole({ role }) {
  const { pathname } = useLocation()

  // done: the first answer has arrived; until then nothing is shown
  const [check, setCheck] = useState({ done: false, user: null, error: '' })

  // When the server last heard from this page (milliseconds)
  const lastContact = useRef(0)

  useEffect(() => {
    // Ignore an answer that arrives after the user has moved on
    let current = true

    getCurrentUser()
      .then((user) => {
        lastContact.current = Date.now()
        if (current) setCheck({ done: true, user, error: '' })
      })
      .catch((error) => {
        if (current) setCheck({ done: true, user: null, error: error.message })
      })

    return () => {
      current = false
    }
  }, [pathname])

  const loggedIn = Boolean(check.user)

  useEffect(() => {
    if (!loggedIn) return undefined

    function stillHere() {
      if (Date.now() - lastContact.current < KEEP_ALIVE_MS) return
      lastContact.current = Date.now()

      getCurrentUser()
        .then((user) => {
          // The session already ended: go to the Login page now
          if (!user) setCheck({ done: true, user: null, error: '' })
        })
        // Server unreachable: the next page change shows the error
        .catch(() => {})
    }

    for (const name of ACTIVITY_EVENTS) {
      window.addEventListener(name, stillHere, { passive: true })
    }

    return () => {
      for (const name of ACTIVITY_EVENTS) {
        window.removeEventListener(name, stillHere)
      }
    }
  }, [loggedIn])

  if (!check.done) {
    return (
      <p className="page" role="status">
        Checking your session…
      </p>
    )
  }

  if (check.error) {
    return (
      <main className="page">
        <EmptyState variant="error" title="Cannot check your session">
          {check.error}
        </EmptyState>
      </main>
    )
  }

  if (!check.user) {
    return <Navigate to="/" replace />
  }

  if (check.user.role !== role) {
    return <Navigate to={HOME_BY_ROLE[check.user.role] ?? '/'} replace />
  }

  return <Outlet context={{ user: check.user }} />
}

export default RequireRole
