import { useRef, useState } from 'react'
import Button from '../../components/Button'
import Card from '../../components/Card'
import InfoList from '../../components/InfoList'
import { createEngineer, generatePassphrase } from '../../services/adminService'
import PasswordField from './PasswordField'

// The Create account form in the details panel (ADM-01), in two steps:
//
//   1. form      name, email, password (typed or Generated) and confirmation
//   2. confirm   the entered details, to Confirm or go Back and change them
//
// The server checks everything again, including the password rules that
// need the full lists (common passwords, the person's own name and email).
// After the account is created the password is not kept or shown anywhere.
//
//   onCreated(engineer)  called with the new account
//   onCancel()           called when the admin closes the form

// The same simple check as the Login page and the server
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const MIN_PASSWORD = 15
const MAX_PASSWORD = 64

const EMPTY = { name: '', email: '', password: '', confirmation: '' }

// The problems the browser can find before asking the server: field → message
function checkFields({ name, email, password, confirmation }) {
  const errors = {}
  if (!name.trim()) errors.name = "Enter the engineer's name."
  if (!email.trim()) errors.email = "Enter the engineer's work email."
  else if (!EMAIL_PATTERN.test(email.trim()))
    errors.email = 'Enter an email address like name@organization.gov.sa.'
  if (!password) errors.password = 'Enter a password, or select Generate.'
  else if ([...password].length < MIN_PASSWORD)
    errors.password = `Use at least ${MIN_PASSWORD} characters. A short phrase works well.`
  else if ([...password].length > MAX_PASSWORD)
    errors.password = `Use at most ${MAX_PASSWORD} characters.`
  if (password && confirmation !== password)
    errors.confirmation = 'The passwords do not match.'
  return errors
}

function CreateEngineer({ onCreated, onCancel }) {
  const [fields, setFields] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  // A problem that is not about one field, e.g. the server is down
  const [formError, setFormError] = useState('')
  // 'form' | 'confirm' | 'saving'
  const [step, setStep] = useState('form')
  const [generating, setGenerating] = useState(false)
  // The confirmation step's own Show/Hide for the password
  const [confirmShown, setConfirmShown] = useState(false)

  const nameRef = useRef(null)
  const emailRef = useRef(null)
  const formRefs = { name: nameRef, email: emailRef }

  function setField(field) {
    return (value) => {
      setFields((current) => ({ ...current, [field]: value }))
      setFormError('')
      if (errors[field]) setErrors((current) => ({ ...current, [field]: undefined }))
    }
  }

  async function generate() {
    setGenerating(true)
    setFormError('')
    try {
      const passphrase = await generatePassphrase()
      setFields((current) => ({ ...current, password: passphrase, confirmation: passphrase }))
      setErrors((current) => ({ ...current, password: undefined, confirmation: undefined }))
    } catch (error) {
      setFormError(error.message)
    }
    setGenerating(false)
  }

  function review(event) {
    event.preventDefault() // stop the browser from reloading the page
    const found = checkFields(fields)
    setErrors(found)
    if (Object.keys(found).length > 0) {
      formRefs[Object.keys(found)[0]]?.current?.focus()
      return
    }
    setConfirmShown(false)
    setStep('confirm')
  }

  async function confirm() {
    setStep('saving')
    try {
      const engineer = await createEngineer({
        name: fields.name.trim(),
        email: fields.email.trim(),
        password: fields.password,
      })
      // Forget the password at once: it is not shown again (ADM-01)
      setFields(EMPTY)
      onCreated(engineer)
    } catch (error) {
      // Back to the form, with the message under the field it is about
      setStep('form')
      if (error.field) setErrors({ [error.field]: error.message })
      else setFormError(error.message)
    }
  }

  if (step !== 'form') {
    const saving = step === 'saving'
    return (
      <Card title="Confirm the new account" className="admin-panel">
        <InfoList
          items={[
            { label: 'Name', value: fields.name.trim() },
            { label: 'Email', value: fields.email.trim().toLowerCase() },
            { label: 'Role', value: 'Traffic engineer' },
            {
              label: 'Password',
              value: (
                <span className="admin-confirm-password">
                  <span className={confirmShown ? 'admin-password-text' : ''}>
                    {confirmShown ? fields.password : '•'.repeat(12)}
                  </span>
                  <button
                    type="button"
                    className="admin-inline-button"
                    onClick={() => setConfirmShown(!confirmShown)}
                    aria-label="Show password"
                    aria-pressed={confirmShown}
                    disabled={saving}
                  >
                    {confirmShown ? 'Hide' : 'Show'}
                  </button>
                </span>
              ),
            },
          ]}
        />
        <p className="admin-field-hint">
          Copy the password before you confirm; it won't be shown again.
        </p>
        <div className="admin-actions">
          <Button variant="secondary" onClick={() => setStep('form')} disabled={saving}>
            Back
          </Button>
          <Button onClick={confirm} disabled={saving}>
            {saving ? 'Creating…' : 'Confirm'}
          </Button>
        </div>
      </Card>
    )
  }

  return (
    <Card title="Create an engineer account" className="admin-panel">
      {formError && (
        <div className="admin-form-error" role="alert">
          {formError}
        </div>
      )}

      <form className="admin-form" onSubmit={review} noValidate>
        <div className="admin-field">
          <label htmlFor="new-name" className="admin-label">
            Name
          </label>
          <input
            ref={nameRef}
            id="new-name"
            className={`admin-input ${errors.name ? 'admin-input-invalid' : ''}`}
            value={fields.name}
            onChange={(event) => setField('name')(event.target.value)}
            autoComplete="off"
            aria-invalid={Boolean(errors.name)}
            aria-describedby={errors.name ? 'new-name-error' : undefined}
          />
          {errors.name && (
            <p id="new-name-error" className="admin-field-error">
              {errors.name}
            </p>
          )}
        </div>

        <div className="admin-field">
          <label htmlFor="new-email" className="admin-label">
            Work email
          </label>
          <input
            ref={emailRef}
            id="new-email"
            type="email"
            className={`admin-input ${errors.email ? 'admin-input-invalid' : ''}`}
            placeholder="name@organization.gov.sa"
            value={fields.email}
            onChange={(event) => setField('email')(event.target.value)}
            autoComplete="off"
            aria-invalid={Boolean(errors.email)}
            aria-describedby={errors.email ? 'new-email-error' : undefined}
          />
          {errors.email && (
            <p id="new-email-error" className="admin-field-error">
              {errors.email}
            </p>
          )}
        </div>

        <PasswordField
          id="new-password"
          label="Password"
          value={fields.password}
          onChange={setField('password')}
          error={errors.password}
          canCopy
          action={
            <button
              type="button"
              className="admin-link-button"
              onClick={generate}
              disabled={generating}
            >
              {generating ? 'Generating…' : 'Generate'}
            </button>
          }
        />
        <p className="admin-field-hint">
          At least 15 characters. A short phrase works well, or select Generate.
        </p>

        <PasswordField
          id="new-confirmation"
          label="Confirm password"
          value={fields.confirmation}
          onChange={setField('confirmation')}
          error={errors.confirmation}
        />

        <div className="admin-actions">
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit">Create account</Button>
        </div>
      </form>
    </Card>
  )
}

export default CreateEngineer
