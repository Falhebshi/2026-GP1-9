import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import loginRoads from '../assets/login-roads.svg'
import Button from '../components/Button'
import ThemeToggle from '../components/ThemeToggle'
import { HOME_BY_ROLE, getCurrentUser, logIn } from '../services/authService'
import './Login.css'

// The Login page, at "/" (the index page): Jaadah's name on an indigo panel with the main roads around the
// study intersection on the left, the sign-in form on the right, and the light / night mode
// switch in the corner.
//
// It logs in through logIn() in services/authService.js, which asks the
// accounts server. After logging in, engineers go to the Network Traffic
// Overview and administrators to the Admin Dashboard (PBI 31).

// A simple check that something looks like an email address. The backend
// still decides whether the account exists.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function Login() {
  const navigate = useNavigate()

  // Someone already logged in goes straight to their first page
  useEffect(() => {
    let current = true

    getCurrentUser()
      .then((user) => {
        if (current && user) {
          navigate(HOME_BY_ROLE[user.role] ?? HOME_BY_ROLE.engineer, { replace: true })
        }
      })
      // Server unreachable: show the form; logging in will say so
      .catch(() => {})

    return () => {
      current = false
    }
  }, [navigate])

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  // Messages under each field, shown after a failed try to log in
  const [fieldErrors, setFieldErrors] = useState({})
  // A message from the login service, e.g. wrong password
  const [formError, setFormError] = useState('')
  const [loading, setLoading] = useState(false)

  // Used to move the cursor to the first field with a problem
  const emailRef = useRef(null)
  const passwordRef = useRef(null)

  function checkFields(trimmedEmail) {
    const errors = {}
    if (!trimmedEmail) {
      errors.email = 'Enter your work email.'
    } else if (!EMAIL_PATTERN.test(trimmedEmail)) {
      errors.email = 'Enter an email address like name@organization.gov.sa.'
    }
    if (!password) errors.password = 'Enter your password.'
    return errors
  }

  // Typing in a field clears its message and the service message, so old
  // errors do not stay on screen after the user has started fixing them
  function handleChange(field, setValue) {
    return (event) => {
      setValue(event.target.value)
      setFormError('')
      if (fieldErrors[field]) {
        setFieldErrors((errors) => ({ ...errors, [field]: undefined }))
      }
    }
  }

  async function handleSubmit(event) {
    event.preventDefault() // stop the browser from reloading the page
    setFormError('')

    const trimmedEmail = email.trim()
    const errors = checkFields(trimmedEmail)
    setFieldErrors(errors)

    if (errors.email) {
      emailRef.current.focus()
      return
    }
    if (errors.password) {
      passwordRef.current.focus()
      return
    }

    setLoading(true)
    try {
      const { user } = await logIn({ email: trimmedEmail, password })
      navigate(HOME_BY_ROLE[user.role] ?? HOME_BY_ROLE.engineer, { replace: true })
    } catch (error) {
      setFormError(error.message)
      setLoading(false)
    }
  }

  return (
    <main className="login">
      <aside className="login-brand-panel">
        {/* The real main roads around the study intersection, coloured like the network map
            (built by jaadah/network_congestion/login_roads.py) */}
        <img className="login-roads" src={loginRoads} alt="" />
        <div className="login-brand-text">
          <p className="login-brand-name">Jaadah</p>
          <p className="login-brand-tagline">Traffic digital twin for Riyadh intersections</p>
        </div>
      </aside>

      <div className="login-theme">
        <ThemeToggle />
      </div>

      <div className="login-panel">
        <h1 className="login-title">Sign in</h1>

        {formError && (
          <div className="login-error" role="alert">
            {formError}
          </div>
        )}

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="login-field">
            <label htmlFor="login-email" className="login-label">
              Email
            </label>
            <input
              ref={emailRef}
              id="login-email"
              type="email"
              className={`login-input ${fieldErrors.email ? 'login-input-invalid' : ''}`}
              placeholder="name@organization.gov.sa"
              autoComplete="username"
              value={email}
              onChange={handleChange('email', setEmail)}
              aria-invalid={Boolean(fieldErrors.email)}
              aria-describedby={fieldErrors.email ? 'login-email-error' : undefined}
              disabled={loading}
            />
            {fieldErrors.email && (
              <p id="login-email-error" className="login-field-error">
                {fieldErrors.email}
              </p>
            )}
          </div>

          <div className="login-field">
            <label htmlFor="login-password" className="login-label">
              Password
            </label>
            <div className="login-password">
              <input
                ref={passwordRef}
                id="login-password"
                type={showPassword ? 'text' : 'password'}
                className={`login-input ${fieldErrors.password ? 'login-input-invalid' : ''}`}
                placeholder="Enter your password"
                autoComplete="current-password"
                value={password}
                onChange={handleChange('password', setPassword)}
                aria-invalid={Boolean(fieldErrors.password)}
                aria-describedby={fieldErrors.password ? 'login-password-error' : undefined}
                disabled={loading}
              />
              {/* The visible word changes; screen readers hear one fixed
                  label plus "pressed" or "not pressed" */}
              <button
                type="button"
                className="login-show"
                onClick={() => setShowPassword(!showPassword)}
                aria-label="Show password"
                aria-pressed={showPassword}
                disabled={loading}
              >
                {showPassword ? 'Hide' : 'Show'}
              </button>
            </div>
            {fieldErrors.password && (
              <p id="login-password-error" className="login-field-error">
                {fieldErrors.password}
              </p>
            )}
          </div>

          <Button type="submit" className="login-submit" disabled={loading}>
            {loading ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        <p className="login-help">Forgot your password? Contact your administrator.</p>
      </div>
    </main>
  )
}

export default Login
