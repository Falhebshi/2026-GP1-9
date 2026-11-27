import { useEffect, useState } from 'react'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import Notice from '../components/Notice'
import PageHeader from '../components/PageHeader'
import { listEngineers } from '../services/adminService'
import CreateEngineer from './admin/CreateEngineer'
import EngineerDetails from './admin/EngineerDetails'
import EngineerList from './admin/EngineerList'
import './admin/AdminDashboard.css'

// The Admin Dashboard, at "/admin": where an administrator lands after
// logging in (PBI 31). Only administrators can open it (RequireRole in
// App.jsx).
//
//   left    the engineer accounts in a card, with how many there are (ADM-02); clicking one
//           selects it
//   right   the panel: the selected engineer's details and account actions
//           (ADM-03, ADM-05, ADM-04), or the Create account form (ADM-01)
function AdminDashboard() {
  // null while loading the first time
  const [engineers, setEngineers] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [creating, setCreating] = useState(false)
  // A line under the header after an action, e.g. "Account created for …":
  // { text, variant } with variant "info" or "warning", or null
  const [message, setMessage] = useState(null)

  // Loads (or reloads) the list; a failed reload keeps the list on screen
  function load() {
    return listEngineers()
      .then((list) => {
        setEngineers(list)
        setLoadError('')
      })
      .catch((error) => setLoadError(error.message))
  }

  useEffect(() => {
    let current = true
    listEngineers()
      .then((list) => {
        if (current) setEngineers(list)
      })
      .catch((error) => {
        if (current) setLoadError(error.message)
      })
    return () => {
      current = false
    }
  }, [])

  function select(id) {
    setSelectedId(id)
    setCreating(false)
    setMessage(null)
  }

  function startCreating() {
    setCreating(true)
    setMessage(null)
  }

  async function handleCreated(engineer) {
    setCreating(false)
    await load()
    setSelectedId(engineer.id)
    setMessage({ text: `Account created for ${engineer.name}.`, variant: 'info' })
  }

  // After an action on the selected engineer (ADM-03, ADM-05)
  async function handleChanged(engineer, text) {
    await load()
    setSelectedId(engineer.id)
    setMessage({ text, variant: 'info' })
  }

  // After deleting the selected engineer (ADM-04)
  async function handleDeleted(engineer) {
    setSelectedId(null)
    await load()
    setMessage({ text: `${engineer.name}'s account was deleted.`, variant: 'info' })
  }

  // The account was deleted in another tab: refresh and say so
  async function handleGone() {
    setSelectedId(null)
    await load()
    setMessage({ text: 'This account no longer exists.', variant: 'warning' })
  }

  const selected = engineers?.find((engineer) => engineer.id === selectedId) ?? null

  let panel
  if (creating) {
    panel = <CreateEngineer onCreated={handleCreated} onCancel={() => setCreating(false)} />
  } else if (selected) {
    panel = (
      <EngineerDetails
        key={selected.id}
        engineer={selected}
        onChanged={handleChanged}
        onDeleted={handleDeleted}
        onGone={handleGone}
      />
    )
  } else {
    panel = (
      <Card className="admin-panel">
        <p className="admin-panel-note">Select an engineer to see their account.</p>
      </Card>
    )
  }

  return (
    <>
      <PageHeader
        title="Admin Dashboard"
        actions={
          <Button onClick={startCreating} disabled={creating}>
            + Create account
          </Button>
        }
      />

      {message && (
        <Notice variant={message.variant} className="admin-message">
          {message.text}
        </Notice>
      )}

      {loadError && !engineers ? (
        <EmptyState variant="error" title="Engineer accounts unavailable">
          {loadError}
        </EmptyState>
      ) : (
        <div className="admin-layout">
          <Card
            title="Engineer accounts"
            action={
              engineers?.length ? (
                <span className="engineer-list-count">
                  {engineers.length} {engineers.length === 1 ? 'engineer' : 'engineers'}
                </span>
              ) : null
            }
            className="admin-list"
          >
            {engineers === null ? (
              <p className="admin-panel-note" role="status">
                Loading engineer accounts…
              </p>
            ) : (
              <EngineerList engineers={engineers} selectedId={selectedId} onSelect={select} />
            )}
          </Card>
          <section className="admin-side" aria-label="Account details">
            {panel}
          </section>
        </div>
      )}
    </>
  )
}

export default AdminDashboard
