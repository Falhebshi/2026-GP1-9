import { useEffect, useState } from 'react'
import AlertCard from '../components/AlertCard'
import Badge from '../components/Badge'
import Button from '../components/Button'
import EmptyState from '../components/EmptyState'
import PageHeader from '../components/PageHeader'
import { getAlerts } from '../services/alertsService'
import './Alerts.css'

// How many cards a section shows before "Show all" is needed
const COLLAPSED_COUNT = 3

// The three sections of the page, in order
const SECTIONS = [
  {
    type: 'current',
    title: 'Current Alerts',
    button: 'Current',
    description: 'Abnormal conditions detected right now.',
  },
  {
    type: 'forecast',
    title: 'Forecast Alerts',
    button: 'Forecast',
    description: 'Potential problems expected soon.',
  },
  {
    type: 'pattern',
    title: 'Pattern Alerts',
    button: 'Patterns',
    description: 'Problems that repeat at similar times.',
  },
]

function Alerts() {
  const [data, setData] = useState(null) // the alerts, once they arrive
  const [error, setError] = useState(null) // the error message, if loading failed

  // Load the alerts once, when the page opens
  useEffect(() => {
    let cancelled = false // true if the user leaves before the data arrives

    getAlerts()
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [])

  // Scroll down to a section when its button is clicked
  function jumpTo(type) {
    document.getElementById(`alerts-${type}`)?.scrollIntoView({ behavior: 'smooth' })
  }

  const header = (
    <PageHeader
      title="Alerts"
      subtitle={`Selected area: ${data?.area ?? '…'}`}
      actions={
        data &&
        SECTIONS.map((section) => (
          <Button
            key={section.type}
            variant="secondary"
            size="sm"
            onClick={() => jumpTo(section.type)}
          >
            {section.button}
            <span className="alerts-jump-count">{data[section.type].length}</span>
          </Button>
        ))
      }
    />
  )

  if (error) {
    return (
      <>
        {header}
        <EmptyState variant="error" title="Alerts unavailable">
          {error}
        </EmptyState>
      </>
    )
  }

  if (!data) {
    return (
      <>
        {header}
        <EmptyState>Loading alerts…</EmptyState>
      </>
    )
  }

  return (
    <>
      {header}

      {SECTIONS.map((section) => (
        <AlertSection
          key={section.type}
          {...section}
          alerts={data[section.type]}
        />
      ))}
    </>
  )
}

// One section: its heading, then a grid of cards (or the empty message).
// A long section shows its first few cards and a button to show the rest.
function AlertSection({ type, title, description, alerts }) {
  const [expanded, setExpanded] = useState(false)

  const hasMore = alerts.length > COLLAPSED_COUNT
  const visible = expanded ? alerts : alerts.slice(0, COLLAPSED_COUNT)

  return (
    <section id={`alerts-${type}`} className="alerts-section">
      <header className="alerts-section-header">
        <span className={`alerts-section-dot alerts-section-dot-${type}`} aria-hidden="true" />
        <h2 className="alerts-section-title">{title}</h2>
        <Badge variant="count">{alerts.length}</Badge>
      </header>
      <p className="alerts-section-description">{description}</p>

      {alerts.length === 0 ? (
        <EmptyState>No alerts are currently available.</EmptyState>
      ) : (
        <div id={`alerts-${type}-cards`} className="alerts-grid">
          {visible.map((alert) => (
            <AlertCard
              key={alert.id}
              type={type}
              title={alert.title}
              details={toRows(type, alert)}
              interventionsTo={
                alert.interventionId ? `/recommendations/${alert.interventionId}` : undefined
              }
            />
          ))}
        </div>
      )}

      {hasMore && (
        <div className="alerts-more">
          <Button
            variant="secondary"
            size="sm"
            aria-expanded={expanded}
            aria-controls={`alerts-${type}-cards`}
            onClick={() => setExpanded(!expanded)}
          >
            {expanded ? 'Show fewer' : `Show all ${alerts.length}`}
          </Button>
        </div>
      )}
    </section>
  )
}

// Turns one alert's data into the rows shown on its card.
// Each type of alert shows different details.
function toRows(type, alert) {
  if (type === 'current') {
    return [
      { label: 'Affected area', value: alert.area },
      { label: 'Detected at', value: alert.detectedAt },
      {
        label: 'Status',
        value: alert.status === 'active' ? <Badge variant="warning">Active</Badge> : undefined,
      },
    ]
  }

  if (type === 'forecast') {
    return [
      { label: 'Affected area', value: alert.area },
      { label: 'Expected in', value: minutes(alert.expectedInMinutes) },
      { label: 'Horizon', value: alert.horizonMinutes != null ? `+${alert.horizonMinutes} min` : undefined },
    ]
  }

  return [
    { label: 'Location', value: alert.location },
    { label: 'When', value: alert.when },
    {
      label: 'How often',
      value: alert.daysSeen != null ? `${alert.daysSeen} of ${alert.daysTotal} days` : undefined,
    },
  ]
}

// 25 becomes "25 min". A missing value stays missing, so the row shows
// "Unavailable" instead of "undefined min".
function minutes(value) {
  return value != null ? `${value} min` : undefined
}

export default Alerts