import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import BrandMark from '../components/BrandMark'
import Button from '../components/Button'
import { logIn } from '../services/authService'
import { CONTACT_EMAIL, CONTACT_HREF } from '../utils/contact'
import './Login.css'

// The Login page, at "/login": the login form in a centered card, with the
// team's email in the footer.
//
// It logs in through logIn() in services/authService.js, which is fake for
// now. To see the error messages, add ?demo=invalid or ?demo=error to the
// page address.

// Where to go after logging in (PBI 31: the Network Traffic Overview)
const AFTER_LOGIN = '/overview'

// For the copyright line in the footer
const YEAR = new Date().getFullYear()

// A simple check that something looks like an email address. The backend
// still decides whether the account exists.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function Login() {
  const navigate = useNavigate()

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
      await logIn({ email: trimmedEmail, password })
      navigate(AFTER_LOGIN)
    } catch (error) {
      setFormError(error.message)
      setLoading(false)
    }
  }

  return (
    <main className="login">
      <div className="login-panel">
        <Link to="/" className="login-brand">
          <BrandMark size="md" />
          Jaadah
        </Link>

        <h1 className="login-title">Log in</h1>
        <p className="login-subtitle">
          Use the account provided by the Jaadah team.
        </p>

        {formError && (
          <div className="login-error" role="alert">
            {formError}
          </div>
        )}

        <form className="login-form" onSubmit={handleSubmit} noValidate>
          <div className="login-field">
            <label htmlFor="login-email" className="login-label">
              Work email
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
            {loading ? 'Logging in…' : 'Log in'}
          </Button>
        </form>

      </div>

      <footer className="login-footer">
        <p>Authorized access only.</p>
        <p>© {YEAR} Jaadah · King Saud University</p>
        <p>
          <a href={CONTACT_HREF} className="login-footer-email">
            <svg className="login-footer-icon" viewBox="0 0 16 16" aria-hidden="true">
              <rect x="1.5" y="3.5" width="13" height="9" rx="1.5" />
              <path d="M2 4.5 8 9l6-4.5" />
            </svg>
            {CONTACT_EMAIL}
          </a>
        </p>
      </footer>
    </main>
  )
}

export default Login
