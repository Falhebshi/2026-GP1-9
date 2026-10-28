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
// intersection and its timeline on the right. The page shows a simulated run (the only real data
// in Sprint 1): the scene plays its analysis period at real speed and starts again at the end,
// and tells the page its time, so the KPIs, the approaches and the timeline follow the 15
// minutes being played. Clicking a bar jumps there. The time bar says "Simulated"; once live
// data exists (source 'live') it shows the clock and "Live" instead. The scene can be shown full
// screen; the selected approach then sits next to it.
function CurrentTraffic() {
  const [data, setData] = useState(null) // the page data, once it arrives
  const [error, setError] = useState(null) // the error message, if loading failed
  const [simError, setSimError] = useState(null)
  const [openApproachId, setOpenApproachId] = useState(null)
  const [now, setNow] = useState(() => Date.now())
  const { ref: sceneRef, fullScreen, toggle: toggleFullScreen } = useFullScreen()
  const [time, setTime] = useState(0) // seconds from the start of the run's analysis period
  const [jumpTo, setJumpTo] = useState(null)

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

  // Live data only: the clock, updated every 15 seconds so the minute is never late
  const live = data?.source === 'live'
  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => setNow(Date.now()), 15000)
    return () => clearInterval(timer)
  }, [live])

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

  const { intersection, run, hasKpis, intervals, timeline, alerts } = data
  // Why there is nothing to play, if so: no run yet, or the run failed
  const runProblem = !run
    ? 'No simulated run is available yet.'
    : run.status === 'failed'
      ? `The simulated run failed: ${run.failureReason}`
      : null
  // Why the KPI box is empty, if it is
  const kpiProblem = runProblem ?? (hasKpis ? null : 'KPIs are not available for this run yet.')
  // the 15 minutes being played, and the time shown: the clock for live data, the run's time
  // for a simulated run
  const index = runProblem
    ? -1
    : Math.min(intervals.length - 1, Math.floor(time / run.intervalSeconds))
  const interval = intervals[index]
  const kpis = interval?.kpis ?? []
  const approaches = interval?.approaches ?? []
  const shownTime = live
    ? new Date(now)
    : new Date(Date.parse(run?.start ?? now) + (runProblem ? 0 : time * 1000))
  const night = darkness(shownTime, intersection.center)
  const openApproach = approaches.find((a) => a.approach_id === openApproachId)
  const kpiInterval = interval ? intervalLabel(interval) : null

  // A bar on the timeline: play from the start of its 15 minutes (null is the newest bar)
  function selectBar(barTime) {
    const target =
      barTime === null ? intervals.length - 1 : timeline.findIndex((b) => b.time === barTime)
    if (target < 0) return
    setTime(target * run.intervalSeconds)
    setJumpTo({ time: target * run.intervalSeconds })
  }

  const details = openApproach && (
    <ApproachDetails approach={openApproach} onClose={() => setOpenApproachId(null)} />
  )

  // the time, its badge and the full screen button: above both columns, or inside the scene
  // in full screen
  const timeBar = (
    <div className="current-traffic-time">
      <span className="current-traffic-time-value">{formatLabel(shownTime)}</span>
      {live ? <Badge variant="success">Live</Badge> : <Badge variant="neutral">Simulated</Badge>}
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
            {kpiProblem && <EmptyState>{kpiProblem}</EmptyState>}
            {!kpiProblem &&
              (kpis.length ? (
                <KpiSummary kpis={kpis} compared="the 15 minutes before" />
              ) : (
                <EmptyState>No KPIs are available for this interval.</EmptyState>
              ))}
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
                error={runProblem ?? simError}
              >
                <TrafficScene3D
                  intersectionId={intersection.id}
                  onTimeChange={setTime}
                  jumpTo={jumpTo}
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
            value={interval?.start ?? null}
            onChange={selectBar}
            live={live}
            emptyMessage={runProblem}
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

// The 15 minutes the KPIs cover, e.g. "08:15–08:30"
function intervalLabel({ start, end }) {
  const time = (iso) =>
    new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${time(start)}–${time(end)}`
}

export default CurrentTraffic
