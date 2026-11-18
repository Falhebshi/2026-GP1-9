import { useOutletContext } from 'react-router-dom'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'

// The Admin Dashboard, at "/admin": where an administrator lands after
// logging in (PBI 31). Only administrators can open it (RequireRole in
// App.jsx). The list of engineer accounts is added by ADM-02.
function AdminDashboard() {
  const { user } = useOutletContext()

  return (
    <>
      <PageHeader title="Admin Dashboard" subtitle={`Logged in as ${user.name}`} />
      <EmptyState title="Engineer accounts">
        The list of engineer accounts will appear here.
      </EmptyState>
    </>
  )
}

export default AdminDashboard
