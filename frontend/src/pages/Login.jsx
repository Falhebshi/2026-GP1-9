import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import BrandMark from '../components/BrandMark'
import Button from '../components/Button'
import intersectionImage from '../assets/login-intersection.jpg'
import { logIn } from '../services/authService'
import './Login.css'

// The Login page, at "/login". Follows the Figma "Login Page" frame:
//   left    a screenshot of the 3D simulation of one intersection, and the
//           project's title and one-line description
//   right   the log-in form, and a note for people without an account
//
// It signs in through logIn() in services/authService.js, which is fake for
// now. To see the error messages, add ?demo=invalid or ?demo=error to the
// page address.

const CURRENT_YEAR = new Date().getFullYear()

// Where to go after signing in
const AFTER_LOGIN = '/overview'

// A simple check that something looks like an email address. The backend
// still decides whether the account exists.
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function Login() {
  const navigate = useNavigate()
  

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [showForgotHelp, setShowForgotHelp] = useState(false)

  // Messages under each field, shown after the first try to sign in
  const [fieldErrors, setFieldErrors] = useState({})
  // A message from the sign-in service, e.g. wrong password
  const [formError, setFormError] = useState('')
  const [loading, setLoading] = useState(false)

  function checkFields() {
    const errors = {}
    if (!email.trim()) {
      errors.email = 'Enter your work email.'
    } else if (!EMAIL_PATTERN.test(email.trim())) {
      errors.email = 'Enter an email address in this format: name@organization.sa.'
    }
    if (!password) errors.password = 'Enter your password.'
    return errors
  }

  async function handleSubmit(event) {
    event.preventDefault() // stop the browser from reloading the page
    setFormError('')

    const errors = checkFields()
    setFieldErrors(errors)
    if (Object.keys(errors).length > 0) return

    setLoading(true)
    try {
      await logIn({ email: email.trim(), password, remember })
      navigate(AFTER_LOGIN)
    } catch (error) {
      setFormError(error.message)
      setLoading(false)
    }
  }

  return (
    <div className="login">
      <aside className="login-side">
        {/* A screenshot from the 3D view, cropped in on the intersection
            (no map controls or overlays). Saved in
            src/assets/login-intersection.jpg */}
        <figure className="login-map">
          <img
            src={intersectionImage}
            alt="3D simulation of the Prince Turki Al-Awwal Rd and Imam Saud Rd intersection, with traffic signals and cars queueing at the lights"
            className="login-map-image"
          />
        </figure>

        <div className="login-side-text">
          <h1 className="login-side-title">
            AI powered Digital Twin For{' '}
            <span className="login-side-ombre">Traffic Flow Management.</span>
          </h1>
          <p className="login-side-intro">
            Monitor live conditions, anticipate emerging congestion, and evaluate suitable interventions.</p>
        </div>
      </aside>

      <main className="login-main">
        <div className="login-panel">
          <Link to="/" className="login-brand">
            <BrandMark size="md" />
            <span>Jaadah</span>
          </Link>

          <h2 className="login-title">Welcome to Jaadah</h2>
          <p className="login-subtitle">
            Sign in to access the traffic intelligence platform.
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
                id="login-email"
                type="email"
                className={`login-input ${fieldErrors.email ? 'login-input-invalid' : ''}`}
                placeholder="name@organization.gov.sa"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
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
                  id="login-password"
                  type={showPassword ? 'text' : 'password'}
                  className={`login-input ${fieldErrors.password ? 'login-input-invalid' : ''}`}
                  placeholder="Enter your password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  aria-invalid={Boolean(fieldErrors.password)}
                  aria-describedby={
                    fieldErrors.password ? 'login-password-error' : undefined
                  }
                  disabled={loading}
                />
                <button
                  type="button"
                  className="login-show"
                  onClick={() => setShowPassword(!showPassword)}
                  aria-pressed={showPassword}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
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

            <div className="login-options">
              <label className="login-remember">
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(event) => setRemember(event.target.checked)}
                  disabled={loading}
                />
                Remember me
              </label>

              <button
                type="button"
                className="login-forgot"
                onClick={() => setShowForgotHelp(!showForgotHelp)}
                aria-expanded={showForgotHelp}
              >
                Forgot password?
              </button>
            </div>

            {/* There is no reset page yet: accounts are managed by an
                administrator. Change this when the backend adds one. */}
            {showForgotHelp && (
              <p className="login-help">
                Ask your system administrator to reset your password.
              </p>
            )}

            <Button type="submit" className="login-submit" disabled={loading}>
              {loading ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>
        </div>

        <footer className="login-footer">
          <p>Authorized access only.</p>
          <p>© {CURRENT_YEAR} Jaadah · King Saud University</p>
        </footer>
      </main>
    </div>
  )
}

export default Login
