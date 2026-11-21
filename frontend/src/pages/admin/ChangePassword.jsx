import { useState } from 'react'
import Button from '../../components/Button'
import { changePassword, generatePassphrase } from '../../services/adminService'
import PasswordField from './PasswordField'
import { checkNewPassword } from './passwordChecks'

// The Change password form in the details panel (ADM-05): a new password
// (typed or Generated) and its confirmation. The server checks it with the
// same rules as every password, using this engineer's name and email, and
// logs the engineer out. After saving, the password is not kept or shown.
//
//   engineer          the selected engineer
//   onSaved(engineer) called with the account after the change
//   onCancel()        called when the administrator cancels; nothing changes
//   onGone()          called when the account no longer exists

const EMPTY = { password: '', confirmation: '' }

function ChangePassword({ engineer, onSaved, onCancel, onGone }) {
  const [fields, setFields] = useState(EMPTY)
  const [errors, setErrors] = useState({})
  const [formError, setFormError] = useState('')
  const [saving, setSaving] = useState(false)
  const [generating, setGenerating] = useState(false)

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
      setFields({ password: passphrase, confirmation: passphrase })
      setErrors({})
    } catch (error) {
      setFormError(error.message)
    }
    setGenerating(false)
  }

  async function save(event) {
    event.preventDefault() // stop the browser from reloading the page
    const found = checkNewPassword(fields.password, fields.confirmation)
    setErrors(found)
    if (Object.keys(found).length > 0) return

    setSaving(true)
    try {
      const updated = await changePassword(engineer.id, fields.password)
      // Forget the password at once: it is not shown again (ADM-05)
      setFields(EMPTY)
      onSaved(updated)
    } catch (error) {
      setSaving(false)
      if (error.gone) onGone()
      else if (error.field) setErrors({ [error.field]: error.message })
      else setFormError(error.message)
    }
  }

  return (
    <form className="admin-form admin-panel-section" onSubmit={save} noValidate>
      <p className="admin-confirm-text admin-section-title">
        Change the password for {engineer.name}
      </p>

      {formError && (
        <div className="admin-form-error" role="alert">
          {formError}
        </div>
      )}

      <PasswordField
        id="change-password"
        label="New password"
        value={fields.password}
        onChange={setField('password')}
        error={errors.password}
        canCopy
        disabled={saving}
        action={
          <button
            type="button"
            className="admin-link-button"
            onClick={generate}
            disabled={generating || saving}
          >
            {generating ? 'Generating…' : 'Generate'}
          </button>
        }
      />
      <p className="admin-field-hint">
        At least 15 characters. A short phrase works well, or select Generate.
      </p>

      <PasswordField
        id="change-confirmation"
        label="Confirm new password"
        value={fields.confirmation}
        onChange={setField('confirmation')}
        error={errors.confirmation}
        disabled={saving}
      />

      <p className="admin-field-hint">
        Copy the password before you save; it won&apos;t be shown again. {engineer.name} will be
        logged out and must use the new password.
      </p>

      <div className="admin-actions">
        <Button variant="secondary" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : 'Save password'}
        </Button>
      </div>
    </form>
  )
}

export default ChangePassword
