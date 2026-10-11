import { useState } from 'react'
import { Link } from 'react-router-dom'
import Badge from './Badge'
import Card from './Card'
import EmptyState from './EmptyState'
import InfoList from './InfoList'
import './AlertList.css'

// A card listing alerts: Active Alerts, Forecast Alerts or Recurring
// Problem Alerts.
//
//   title          heading of the card, e.g. "Active Alerts"
//   alerts         the alerts, as a list of objects:
//                    id               unique id (required)
//                    title            e.g. "Queue spillback" (required)
//                    subtitle         small grey line, e.g. "North approach · 2 min ago"
//                    details          rows for an InfoList. If present, the
//                                     alert can be clicked open to show them.
//                    interventionsTo  URL of its interventions. If present,
//                                     a "View interventions" link is shown.
//   emptyMessage   text shown when the list is empty
//   error          text shown instead of the list when alerts failed to load
function AlertList({
  title,
  alerts = [],
  emptyMessage = 'No alerts are currently available.',
  error,
  className = '',
}) {
  // Which alert is open. Only one at a time; null means none.
  const [openId, setOpenId] = useState(null)

  // The count badge appears only when there is something to count
  const countBadge =
    !error && alerts.length > 0 ? (
      <Badge variant="count">{alerts.length}</Badge>
    ) : null

  return (
    <Card title={title} action={countBadge} className={className}>
      {error && (
        <EmptyState variant="error" title="Alerts unavailable">
          {error}
        </EmptyState>
      )}

      {!error && alerts.length === 0 && <EmptyState>{emptyMessage}</EmptyState>}

      {!error && alerts.length > 0 && (
        <ul className="alert-list">
          {alerts.map((alert) => {
            const canOpen = Boolean(alert.details)
            const isOpen = canOpen && alert.id === openId

            const text = (
              <span className="alert-text">
                <span className="alert-title">{alert.title}</span>
                {alert.subtitle && (
                  <span className="alert-subtitle">{alert.subtitle}</span>
                )}
              </span>
            )

            return (
              <li
                key={alert.id}
                className={`alert-item ${isOpen ? 'open' : ''}`}
              >
                <div className="alert-header">
                  {canOpen ? (
                    <button
                      type="button"
                      className="alert-toggle"
                      aria-expanded={isOpen}
                      // Clicking the open alert closes it; clicking another opens that one
                      onClick={() => setOpenId(isOpen ? null : alert.id)}
                    >
                      <span className="alert-chevron" aria-hidden="true" />
                      {text}
                    </button>
                  ) : (
                    text
                  )}

                  {alert.interventionsTo && (
                    <Link to={alert.interventionsTo} className="alert-link">
                      View interventions →
                    </Link>
                  )}
                </div>

                {isOpen && (
                  <div className="alert-details">
                    <InfoList items={alert.details} />
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </Card>
  )
}

export default AlertList