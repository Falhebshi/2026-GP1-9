import Badge from '../../components/Badge'
import EmptyState from '../../components/EmptyState'
import { STATUS_LABELS, STATUS_VARIANTS } from './accountFormat'

// The list of engineer accounts on the Admin Dashboard (ADM-02): name,
// email and status. Clicking a row selects that engineer.
//
//   engineers   [{ id, name, email, status }], already ordered by name
//   selectedId  the selected engineer's id, or null
//   onSelect    called with an engineer's id when their row is clicked

function EngineerList({ engineers, selectedId, onSelect }) {
  if (engineers.length === 0) {
    return (
      <EmptyState title="No engineer accounts yet">
        Create an account for each traffic engineer who needs Jaadah.
      </EmptyState>
    )
  }

  return (
    <div className="engineer-list">
      <p className="engineer-list-count">
        {engineers.length} {engineers.length === 1 ? 'engineer' : 'engineers'}
      </p>
      <ul className="engineer-rows">
        {engineers.map((engineer) => (
          <li key={engineer.id}>
            <button
              type="button"
              className={`engineer-row ${engineer.id === selectedId ? 'engineer-row-selected' : ''}`}
              aria-pressed={engineer.id === selectedId}
              onClick={() => onSelect(engineer.id)}
            >
              <span className="engineer-row-text">
                <span className="engineer-row-name">{engineer.name}</span>
                <span className="engineer-row-email">{engineer.email}</span>
              </span>
              <Badge variant={STATUS_VARIANTS[engineer.status]}>
                {STATUS_LABELS[engineer.status]}
              </Badge>
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}

export default EngineerList
