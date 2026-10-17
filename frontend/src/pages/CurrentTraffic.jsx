import { useEffect, useState } from 'react'
import AlertList from '../components/AlertList'
import Badge from '../components/Badge'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import HistoricalTimeline from '../components/HistoricalTimeline'
import KpiTile from '../components/KpiTile'
import LocationSummary from '../components/LocationSummary'
import SimulationViewport from '../components/SimulationViewport'
import TrafficScene3D from '../components/TrafficScene3D'
import { getCurrentTraffic } from '../services/currentTrafficService'
import { darkness } from '../utils/daylight'
import './CurrentTraffic.css'

// Current Traffic page: the 3D intersection, the last 24 hours of congestion, KPIs and alerts.
// There's no play bar here, so the scene just loops. Picking an older bar on the timeline
// switches the label to "Historical" and sets how dark the scene is from that time.
function CurrentTraffic() {
  const [data, setData] = useState(null) // the page data, once it arrives
  const [error, setError] = useState(null) // the error message, if loading failed
  const [selectedTime, setSelectedTime] = useState(null) // null = latest (live)
  const [simError, setSimError] = useState(null)

  // Load the data once, when the page opens
  useEffect(() => {
    let cancelled = false // true if the user leaves before the data arrives

    getCurrentTraffic()
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

  if (error) {
    return (
      <EmptyState variant="error" title="Current traffic unavailable">
        {error}
      </EmptyState>
    )
  }

  if (!data) {
    return <EmptyState>Loading current traffic…</EmptyState>
  }

  const { intersection, timeline, kpis, alerts, approaches } = data
  const shownTime = selectedTime ?? timeline[timeline.length - 1]?.time
  const timeLabel = shownTime ? formatLabel(new Date(shownTime)) : undefined
  const night = shownTime ? darkness(new Date(shownTime), intersection.center) : 0

  return (
    <div className="current-traffic">
      <div className="current-traffic-sim">
        {/* time shown above the map, on the right */}
        {timeLabel && (
          <div className="current-traffic-time">
            <span className="current-traffic-time-value">{timeLabel}</span>
            {selectedTime === null ? (
              <Badge variant="success">Live</Badge>
            ) : (
              <Badge variant="warning">Historical</Badge>
            )}
          </div>
        )}

        <SimulationViewport
          height={560}
          overlay={<LocationSummary intersection={intersection} />}
          error={simError}
        >
          <TrafficScene3D
            intersectionId={intersection.id}
            center={intersection.center}
            bounds={intersection.bounds}
            night={night}
            approaches={approaches}
            onError={setSimError}
          />
        </SimulationViewport>
      </div>

      <HistoricalTimeline
        title="Traffic Timeline"
        bars={timeline}
        value={selectedTime}
        onChange={setSelectedTime}
      />

      <div className="current-traffic-row">
        <Card title="Current KPIs">
          {kpis.length ? (
            <div className="current-traffic-kpis">
              {kpis.map((kpi) => (
                <KpiTile key={kpi.label} {...kpi} />
              ))}
            </div>
          ) : (
            <EmptyState>No KPIs are available for this interval.</EmptyState>
          )}
        </Card>

        <AlertList title="Active Alerts" alerts={alerts} />
      </div>
    </div>
  )
}

// e.g. "Sat 10 Oct, 21:30"
function formatLabel(date) {
  const day = date
    .toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
    .replace(',', '')
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${day}, ${time}`
}

export default CurrentTraffic
