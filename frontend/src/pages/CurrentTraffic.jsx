import { useState } from 'react'
import AlertList from '../components/AlertList'
import Badge from '../components/Badge'
import Card from '../components/Card'
import HistoricalTimeline from '../components/HistoricalTimeline'
import KpiTile from '../components/KpiTile'
import LocationSummary from '../components/LocationSummary'
import SimulationViewport from '../components/SimulationViewport'
import TrafficScene3D from '../components/TrafficScene3D'
import {
  INTERSECTION,
  SAMPLE_ALERTS,
  SAMPLE_APPROACHES,
  SAMPLE_KPIS,
  sampleTimelineBars,
} from '../services/currentTrafficData'
import { darkness } from '../services/daylight'
import './CurrentTraffic.css'

// Current Traffic page: the 3D intersection, the last 24 hours of congestion, KPIs and alerts.
// There's no play bar here, so the scene just loops. Picking an older bar on the timeline
// switches the label to "Historical" and sets how dark the scene is from that time.
function CurrentTraffic() {
  const [bars] = useState(() => sampleTimelineBars())
  const [selectedTime, setSelectedTime] = useState(null) // null = latest (live)
  const [simError, setSimError] = useState(null)

  const shownTime = selectedTime ?? bars[bars.length - 1]?.time
  const timeLabel = shownTime ? formatLabel(new Date(shownTime)) : undefined
  const night = shownTime ? darkness(new Date(shownTime), INTERSECTION.center) : 0

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
          overlay={<LocationSummary intersection={INTERSECTION} />}
          error={simError}
        >
          <TrafficScene3D
            intersectionId={INTERSECTION.id}
            center={INTERSECTION.center}
            bounds={INTERSECTION.bounds}
            night={night}
            approaches={SAMPLE_APPROACHES}
            onError={setSimError}
          />
        </SimulationViewport>
      </div>

      <HistoricalTimeline
        title="Traffic Timeline"
        bars={bars}
        value={selectedTime}
        onChange={setSelectedTime}
      />

      <div className="current-traffic-row">
        <Card title="Current KPIs">
          <div className="current-traffic-kpis">
            {SAMPLE_KPIS.map((kpi) => (
              <KpiTile key={kpi.label} {...kpi} />
            ))}
          </div>
        </Card>

        <AlertList title="Active Alerts" alerts={SAMPLE_ALERTS} />
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
