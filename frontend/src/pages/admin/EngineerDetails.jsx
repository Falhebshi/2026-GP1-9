import { useState } from 'react'
import Badge from '../../components/Badge'
import Button from '../../components/Button'
import Card from '../../components/Card'
import InfoList from '../../components/InfoList'
import { setStatus } from '../../services/adminService'
import { STATUS_LABELS, STATUS_VARIANTS, createdDate } from './accountFormat'

// The details panel for the selected engineer (ADM-02), with the account
// actions:
//
//   Deactivate / Activate   ADM-03; deactivating asks for confirmation first
//
//   engineer              { id, name, email, status, created_at }
//   onChanged(engineer, message)
//                         called after an action, with the updated account
//                         and a line to show to the administrator
//   onGone()              called when the account no longer exists (another
//                         tab deleted it)
//
// The parent gives each engineer their own panel (key={engineer.id}), so a
// half-finished action never carries over to another engineer.
function EngineerDetails({ engineer, onChanged, onGone }) {
  // 'view' | 'confirm-deactivate'
  const [mode, setMode] = useState('view')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function changeStatus(status, message) {
    setBusy(true)
    setError('')
    try {
      const updated = await setStatus(engineer.id, status)
      setMode('view')
      onChanged(updated, message)
    } catch (failure) {
      // Only the server's "no longer exists" means the account was deleted
      if (failure.gone) onGone()
      else setError(failure.message)
    }
    setBusy(false)
  }

  const details = (
    <InfoList
      items={[
        { label: 'Email', value: engineer.email },
        {
          label: 'Status',
          value: (
            <Badge variant={STATUS_VARIANTS[engineer.status]}>
              {STATUS_LABELS[engineer.status]}
            </Badge>
          ),
        },
        { label: 'Created', value: createdDate(engineer.created_at) },
      ]}
    />
  )

  const errorBox = error && (
    <div className="admin-form-error admin-panel-error" role="alert">
      {error}
    </div>
  )

  if (mode === 'confirm-deactivate') {
    return (
      <Card title={engineer.name} className="admin-panel">
        {details}
        {errorBox}
        <p className="admin-confirm-text">
          Deactivate {engineer.name}? They&apos;ll be logged out at once and can&apos;t log in
          until the account is activated again.
        </p>
        <div className="admin-actions">
          <Button variant="secondary" onClick={() => setMode('view')} disabled={busy}>
            Cancel
          </Button>
          <Button
            onClick={() =>
              changeStatus('inactive', `${engineer.name}'s account is deactivated.`)
            }
            disabled={busy}
          >
            {busy ? 'Deactivating…' : 'Deactivate'}
          </Button>
        </div>
      </Card>
    )
  }

  return (
    <Card title={engineer.name} className="admin-panel">
      {details}
      {errorBox}
      <div className="admin-actions admin-actions-start">
        {engineer.status === 'active' ? (
          <Button variant="secondary" onClick={() => setMode('confirm-deactivate')}>
            Deactivate
          </Button>
        ) : (
          <Button
            variant="secondary"
            onClick={() => changeStatus('active', `${engineer.name}'s account is active again.`)}
            disabled={busy}
          >
            {busy ? 'Activating…' : 'Activate'}
          </Button>
        )}
      </div>
    </Card>
  )
}

export default EngineerDetails
