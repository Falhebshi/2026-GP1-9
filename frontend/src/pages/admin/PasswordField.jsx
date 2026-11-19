import { useState } from 'react'

// A password input that is hidden by default and can be shown or hidden
// (ADM-01, ADM-05), with an optional Copy button.
//
//   id, label    the input's id and its label text
//   value        the password
//   onChange     called with the new text when the user types
//   error        a message shown under the field, or ''
//   canCopy      shows a Copy button that copies the password
//   action       anything to show next to the label, e.g. a Generate button
//   disabled     while saving
//   autoComplete "new-password" by default, so browsers suggest one

// How long "Copied" stays on the button
const COPIED_MS = 2000

function PasswordField({
  id,
  label,
  value,
  onChange,
  error = '',
  canCopy = false,
  action = null,
  disabled = false,
  autoComplete = 'new-password',
}) {
  const [shown, setShown] = useState(false)
  // '' | 'copied' | 'failed'
  const [copyState, setCopyState] = useState('')

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
    setTimeout(() => setCopyState(''), COPIED_MS)
  }

  const errorId = `${id}-error`

  return (
    <div className="admin-field">
      <div className="admin-label-row">
        <label htmlFor={id} className="admin-label">
          {label}
        </label>
        {action}
      </div>

      <div className="admin-password">
        <input
          id={id}
          type={shown ? 'text' : 'password'}
          className={`admin-input ${error ? 'admin-input-invalid' : ''}`}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          aria-invalid={Boolean(error)}
          aria-describedby={error ? errorId : undefined}
          disabled={disabled}
          spellCheck={false}
        />
        {/* The visible word changes; screen readers hear one fixed label
            plus "pressed" or "not pressed" */}
        <button
          type="button"
          className="admin-inline-button"
          onClick={() => setShown(!shown)}
          aria-label={`Show ${label.toLowerCase()}`}
          aria-pressed={shown}
          disabled={disabled}
        >
          {shown ? 'Hide' : 'Show'}
        </button>
        {canCopy && (
          <button
            type="button"
            className="admin-inline-button"
            onClick={copy}
            disabled={disabled || !value}
          >
            {copyState === 'copied' ? 'Copied' : 'Copy'}
          </button>
        )}
      </div>

      {copyState === 'failed' && (
        <p className="admin-field-hint" role="status">
          Copying is not available here. Select the password and copy it yourself.
        </p>
      )}
      {error && (
        <p id={errorId} className="admin-field-error">
          {error}
        </p>
      )}
    </div>
  )
}

export default PasswordField
