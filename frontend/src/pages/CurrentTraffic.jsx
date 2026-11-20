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
import Notice from '../components/Notice'
import SimulationViewport from '../components/SimulationViewport'
import TrafficScene3D from '../components/TrafficScene3D'
import useFullScreen from '../hooks/useFullScreen'
import { getCurrentTraffic } from '../services/currentTrafficService'
import { darkness } from '../utils/daylight'
import './CurrentTraffic.css'

// Current Traffic page: the KPIs, alerts and the selected approach on the left, the 3D
// intersection and its timeline on the right. The page shows the live run when the live update
// loop has published one, and otherwise the committed sample run, labelled as a sample. The scene
// plays the run's analysis period at real speed and tells the page its time, so the KPIs, the
// approaches and the timeline follow the 15 minutes being played. Clicking a bar jumps there.
// A live run is checked for a new interval every minute; while the newest bar is selected, the
// page follows each new interval. Intervals without sensor data (estimated traffic) show "No
// sensor data" instead of KPIs and cars, and the newest interval is marked as provisional. The
// scene can be shown full screen; the selected approach then sits next to it.
function CurrentTraffic() {
  const [data, setData] = useState(null) // the page data, once it arrives
  const [error, setError] = useState(null) // the error message, if loading failed
  const [simError, setSimError] = useState(null)
  const [openApproachId, setOpenApproachId] = useState(null)
  const { ref: sceneRef, fullScreen, toggle: toggleFullScreen } = useFullScreen()
  const [time, setTime] = useState(0) // seconds from the start of the run's analysis period
  const [jumpTo, setJumpTo] = useState(null)
  // live: follow the live clock (liveClock below). A new interval builds the scene again, and
  // the scene reports its time, so the KPIs follow within a second. Clicking an earlier bar
  // stops following; clicking the newest bar follows again
  const [followLatest, setFollowLatest] = useState(true)
  // live: true while an interval of the run before the newest one (live/previous/) is shown
  const [onPrevious, setOnPrevious] = useState(false)
  const [openedAt] = useState(() => Date.now()) // the time shown when there is no run

  // Load the data when the page opens
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

  // Live run only: look for a new interval or a change of the loop's state every minute
  const live = data?.source === 'live'
  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => {
      getCurrentTraffic()
        .then((result) => {
          setData((current) =>
            result.live?.version !== current?.live?.version ||
            result.live?.state !== current?.live?.state ||
            result.live?.stale !== current?.live?.stale ||
            result.source !== current?.source
              ? result
              : current,
          )
        })
        .catch(() => {}) // keep showing what is there; the next minute tries again
    }, POLL_MS)
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

  const { intersection, isSample, alerts } = data
  const liveInfo = data.live
  // Live: the timeline covers the last 24 hours, the run before the newest one (previous)
  // and the newest run. The scene, the KPIs and the clock show the run the selected bar is in.
  const previous = data.previous ?? null
  const shown = onPrevious && previous ? previous : data
  const { run, hasKpis, isTest, intervals } = shown
  const timeline = [...(previous?.timeline ?? []), ...data.timeline]
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
  // the run's own time (data time): a live run's traffic is the replay's, not today's clock
  const shownTime = new Date(
    (run ? Date.parse(run.start) : openedAt) + (runProblem ? 0 : time * 1000),
  )
  const night = darkness(shownTime, intersection.center)
  const openApproach = approaches.find((a) => a.approach_id === openApproachId)
  const kpiInterval = interval
    ? `${intervalLabel(interval)}${interval.provisional ? ' (provisional)' : ''}`
    : null
  const following = live && followLatest && !runProblem && shown === data
  // Live: where the scene is now, in seconds from the start of the analysis period. The scene
  // plays the traffic at the time it happened in data time, LIVE_DELAY behind it: by then that
  // moment is always simulated (an interval arrives after it ends, the loop stops 60 s early
  // and takes up to about a minute, and the page looks every minute). It is worked out from
  // the clock, so reloading the page or opening it elsewhere shows the same moment. If the
  // simulation has not got there (the loop is late or stopped), it waits at its end.
  const liveClock = following
    ? () => {
        const dataNow = Date.now() - liveInfo.clockOffsetMs - LIVE_DELAY_MS
        const end = (liveInfo.simulatedUntilSeconds ?? 0) - run.analysisStartSeconds
        return Math.max(0, Math.min((dataNow - Date.parse(run.start)) / 1000, end))
      }
    : null
  // Live: where the scene must not draw cars, in seconds from the run start
  const hiddenRanges = intervals.flatMap((item, i) =>
    item.noSensorData
      ? [
          [
            run.analysisStartSeconds + i * run.intervalSeconds,
            run.analysisStartSeconds + (i + 1) * run.intervalSeconds,
          ],
        ]
      : [],
  )

  // A bar on the timeline: play from the start of its 15 minutes (null is the newest bar). A bar
  // of the previous run switches the scene to that run; the newest bar follows the live clock.
  function selectBar(barTime) {
    const inPrevious =
      barTime !== null && previous ? previous.timeline.findIndex((b) => b.time === barTime) : -1
    const target =
      inPrevious >= 0
        ? inPrevious
        : barTime === null
          ? data.intervals.length - 1
          : data.timeline.findIndex((b) => b.time === barTime)
    if (target < 0) return
    const seconds = target * (inPrevious >= 0 ? previous : data).run.intervalSeconds
    setOnPrevious(inPrevious >= 0)
    setFollowLatest(barTime === null)
    setTime(seconds)
    setJumpTo({ time: seconds })
  }

  const details = openApproach && (
    <ApproachDetails approach={openApproach} onClose={() => setOpenApproachId(null)} />
  )

  // the time, its badge and the full screen button: above both columns, or inside the scene
  // in full screen
  const timeBar = (
    <div className="current-traffic-time">
      <span className="current-traffic-time-value">{formatLabel(shownTime)}</span>
      {timeBadge({ live, liveInfo, following })}
      <Button size="sm" variant="secondary" onClick={toggleFullScreen}>
        {fullScreen ? 'Exit full screen' : 'Full screen'}
      </Button>
    </div>
  )

  return (
    <div className="current-traffic">
      {/* Test files are marked "is_test"; a real run has no mark, so this goes away by itself */}
      {isTest && (
        <Notice variant="warning">
          Test data: the vehicles and KPIs come from a test run with made-up demand, not from the
          baseline simulation. The alerts are samples.
        </Notice>
      )}
      {isSample && (
        <Notice variant="info">
          Sample run: no live run has been published, so the page shows the committed sample of a
          simulated run. Start the live update loop (simulation/scripts/run_live.py) to see live
          traffic.
        </Notice>
      )}
      {live && liveInfo.state === 'paused' && <Notice variant="warning">{liveInfo.message}</Notice>}
      {live && liveInfo.state === 'waiting' && (
        <Notice variant="warning">
          {liveInfo.message} The results up to {formatTime(liveInfo.dataUntil)} (data time) are
          shown.
        </Notice>
      )}
      {live && liveInfo.state === 'starting' && (
        <Notice variant="info">
          {liveInfo.message} Until then, the previous run up to {formatTime(liveInfo.dataUntil)} is
          shown.
        </Notice>
      )}
      {live && liveInfo.state === 'stopped' && (
        <Notice variant="warning">
          Live updates have stopped. The results up to {formatTime(liveInfo.dataUntil)} are shown.
        </Notice>
      )}
      {live && liveInfo.state !== 'stopped' && liveInfo.stale && (
        <Notice variant="warning">
          Live updates are not arriving: the live update loop last reported at{' '}
          {formatTime(liveInfo.updatedAt)}. The results up to {formatTime(liveInfo.dataUntil)} (data
          time) are shown.
        </Notice>
      )}
      {!fullScreen && timeBar}

      <div className="current-traffic-layout">
        <aside className="current-traffic-side">
          {!fullScreen && details}

          <Card title="Current KPIs" action={kpiInterval}>
            {kpiProblem && <EmptyState>{kpiProblem}</EmptyState>}
            {!kpiProblem && interval?.noSensorData && (
              <EmptyState title="No sensor data">
                The detectors sent no data for these 15 minutes, so the traffic was estimated from
                earlier days. Results from estimated traffic are not shown.
              </EmptyState>
            )}
            {!kpiProblem &&
              !interval?.noSensorData &&
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
                footer={
                  interval?.noSensorData ? (
                    <span className="current-traffic-no-data">
                      No sensor data for {intervalLabel(interval)}: the cars are not shown.
                    </span>
                  ) : null
                }
              >
                <TrafficScene3D
                  key={`${shown === data ? '' : 'previous|'}${liveInfo?.version ?? 'sample'}`}
                  scenario={shown.scenario}
                  startAt={time}
                  clock={liveClock}
                  hiddenRanges={hiddenRanges}
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

// How often a live run is checked for a new interval
const POLL_MS = 60 * 1000
// How far the live scene plays behind the data's own time (see liveClock)
const LIVE_DELAY_MS = 20 * 60 * 1000
const LIVE_TITLE =
  'Following the live data. The traffic is shown 20 minutes after it happened, the time it ' +
  'takes for the detector data to arrive and be simulated. The time shown is the time of the traffic.'

// The badge next to the time: what is on screen
function timeBadge({ live, liveInfo, following }) {
  if (!live) return <Badge variant="neutral">Simulated</Badge>
  if (liveInfo.state === 'paused') return <Badge variant="warning">Paused</Badge>
  if (liveInfo.state === 'starting') return <Badge variant="neutral">Starting</Badge>
  if (liveInfo.state === 'stopped' || liveInfo.state === 'waiting' || liveInfo.stale)
    return <Badge variant="warning">Not updating</Badge>
  return following ? (
    <span title={LIVE_TITLE}>
      <Badge variant="success">Live</Badge>
    </span>
  ) : (
    <Badge variant="neutral">Earlier</Badge>
  )
}

// e.g. "21:30", or "unknown" without a time
function formatTime(iso) {
  if (!iso) return 'unknown'
  return new Date(iso).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
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
