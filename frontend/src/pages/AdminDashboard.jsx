import { useEffect, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
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
//   left    the engineer accounts (ADM-02); clicking one selects it
//   right   the panel: the selected engineer's details, or the Create
//           account form (ADM-01)
function AdminDashboard() {
  const { user } = useOutletContext()

  // null while loading the first time
  const [engineers, setEngineers] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [creating, setCreating] = useState(false)
  // A line under the header after an action, e.g. "Account created for …"
  const [message, setMessage] = useState('')

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
    setMessage('')
  }

  function startCreating() {
    setCreating(true)
    setMessage('')
  }

  async function handleCreated(engineer) {
    setCreating(false)
    await load()
    setSelectedId(engineer.id)
    setMessage(`Account created for ${engineer.name}.`)
  }

  const selected = engineers?.find((engineer) => engineer.id === selectedId) ?? null

  let panel
  if (creating) {
    panel = <CreateEngineer onCreated={handleCreated} onCancel={() => setCreating(false)} />
  } else if (selected) {
    panel = <EngineerDetails engineer={selected} />
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
        subtitle={`Logged in as ${user.name}`}
        actions={
          <Button onClick={startCreating} disabled={creating}>
            Create account
          </Button>
        }
      />

      {message && <Notice className="admin-message">{message}</Notice>}

      {loadError && !engineers ? (
        <EmptyState variant="error" title="Engineer accounts unavailable">
          {loadError}
        </EmptyState>
      ) : (
        <div className="admin-layout">
          <section className="admin-list" aria-label="Engineer accounts">
            {engineers === null ? (
              <p className="admin-panel-note" role="status">
                Loading engineer accounts…
              </p>
            ) : (
              <EngineerList engineers={engineers} selectedId={selectedId} onSelect={select} />
            )}
          </section>
          <section className="admin-side" aria-label="Account details">
            {panel}
          </section>
        </div>
      )}
    </>
  )
}

export default AdminDashboard
