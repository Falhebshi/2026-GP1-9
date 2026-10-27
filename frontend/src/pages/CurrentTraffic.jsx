import { useEffect, useState } from 'react'
import AlertList from '../components/AlertList'
import { ApproachDetails } from '../components/ApproachPanel'
import Badge from '../components/Badge'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import HistoricalTimeline from '../components/HistoricalTimeline'
import KpiSummary from '../components/KpiSummary'
import LocationSummary from '../components/LocationSummary'
import SimulationViewport from '../components/SimulationViewport'
import TrafficScene3D from '../components/TrafficScene3D'
import useFullScreen from '../hooks/useFullScreen'
import { getCurrentTraffic } from '../services/currentTrafficService'
import { darkness } from '../utils/daylight'
import './CurrentTraffic.css'

// Current Traffic page: the KPIs, alerts and the selected approach on the left, the 3D
// intersection and the last 24 hours of congestion on the right. There's no play bar here, so
// the scene just loops. Picking an older bar on the timeline switches the label to
// "Historical" and sets how dark the scene is from that time. The scene can be shown full
// screen; the selected approach then sits next to it.
function CurrentTraffic() {
  const [data, setData] = useState(null) // the page data, once it arrives
  const [error, setError] = useState(null) // the error message, if loading failed
  const [selectedTime, setSelectedTime] = useState(null) // null = latest (live)
  const [simError, setSimError] = useState(null)
  const [openApproachId, setOpenApproachId] = useState(null)
  const [now, setNow] = useState(() => Date.now())
  const { ref: sceneRef, fullScreen, toggle: toggleFullScreen } = useFullScreen()

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

  // The live clock, updated every 15 seconds so the minute is never late
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 15000)
    return () => clearInterval(timer)
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
  const live = selectedTime === null
  // live: the current time; historical: the start of the chosen 15-minute bar
  const shownTime = live ? new Date(now) : new Date(selectedTime)
  const night = darkness(shownTime, intersection.center)
  const openApproach = approaches.find((a) => a.approach_id === openApproachId)
  const kpiInterval = kpis[0] ? intervalLabel(kpis[0].current) : null

  const details = openApproach && (
    <ApproachDetails approach={openApproach} onClose={() => setOpenApproachId(null)} />
  )

  // the time, its badge and the full screen button: above both columns, or inside the scene
  // in full screen
  const timeBar = (
    <div className="current-traffic-time">
      <span className="current-traffic-time-value">{formatLabel(shownTime)}</span>
      {live ? <Badge variant="success">Live</Badge> : <Badge variant="warning">Historical</Badge>}
      <Button size="sm" variant="secondary" onClick={toggleFullScreen}>
        {fullScreen ? 'Exit full screen' : 'Full screen'}
      </Button>
    </div>
  )

  return (
    <div className="current-traffic">
      {!fullScreen && timeBar}

      <div className="current-traffic-layout">
        <aside className="current-traffic-side">
          {!fullScreen && details}

          <Card title="Current KPIs" action={kpiInterval}>
            {kpis.length ? (
              <KpiSummary kpis={kpis} compared="the 15 minutes before" />
            ) : (
              <EmptyState>No KPIs are available for this interval.</EmptyState>
            )}
          </Card>

          <AlertList title="Active Alerts" alerts={alerts} />
        </aside>

        <div className="current-traffic-main">
          <div ref={sceneRef} className="current-traffic-scene">
            {fullScreen && timeBar}

            <div className="current-traffic-stage">
              {fullScreen && details && (
                <div className="current-traffic-fullscreen-side">{details}</div>
              )}
              <SimulationViewport
                height={fullScreen ? '100%' : 560}
                className="current-traffic-viewport"
                overlay={<LocationSummary intersection={intersection} />}
                error={simError}
              >
                <TrafficScene3D
                  intersectionId={intersection.id}
                  center={intersection.center}
                  bounds={intersection.bounds}
                  night={night}
                  approaches={approaches}
                  openApproachId={openApproachId}
                  onApproachChange={setOpenApproachId}
                  onError={setSimError}
                />
              </SimulationViewport>
            </div>
          </div>

          <HistoricalTimeline
            title="Traffic Timeline"
            bars={timeline}
            value={selectedTime}
            onChange={setSelectedTime}
          />
        </div>
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

// The 15 minutes the KPIs cover, e.g. "18:00–18:15"
function intervalLabel(result) {
  const time = (iso) =>
    new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${time(result.interval_start)}–${time(result.interval_end)}`
}

export default CurrentTraffic
