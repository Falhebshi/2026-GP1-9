import { useEffect, useRef, useState } from 'react'
import AlertList from '../components/AlertList'
import { ApproachDetails } from '../components/ApproachPanel'
import Badge from '../components/Badge'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import HistoricalTimeline from '../components/HistoricalTimeline'
import IntervalSlider from '../components/IntervalSlider'
import KpiSummary from '../components/KpiSummary'
import LocationSummary from '../components/LocationSummary'
import Notice from '../components/Notice'
import PlayPauseIcon from '../components/PlayPauseIcon'
import SimulationViewport from '../components/SimulationViewport'
import TrafficScene3D from '../components/TrafficScene3D'
import useFullScreen from '../hooks/useFullScreen'
import { getCurrentTraffic, withGaps } from '../services/currentTrafficService'
import { darkness } from '../utils/daylight'
import { RIYADH_TIME_ZONE } from '../utils/riyadhTime'
import './CurrentTraffic.css'

// Current Traffic page: the KPIs, alerts and the selected approach on the left, the 3D
// intersection and its timeline on the right. The page shows the live run when the live update
// loop has published one, and otherwise the committed sample run, labelled as a sample. The scene
// plays the run's analysis period at real speed and tells the page its time, so the KPIs, the
// approaches and the timeline follow the 15 minutes being played. Clicking a bar jumps there.
// A live run is checked for a new interval every minute; while the newest bar is selected, the
// page follows each new interval. Intervals without detector data (estimated traffic) show "No
// detector data" instead of KPIs and cars, and the newest interval is marked as provisional. The
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
  // live: the run ID of the earlier run whose interval is shown (live/previous/, or after
  // restarts one in live/earlier/), or null for the newest run
  const [shownId, setShownId] = useState(null)
  // PBI 15: the playback is paused, and the timeline shows one interval as a time slider
  const [paused, setPaused] = useState(false)
  const [zoomed, setZoomed] = useState(false)
  // full screen: the timeline floats over the scene when opened, as on Network Traffic Overview;
  // closed, so the scene gets the room
  const [floatingOpen, setFloatingOpen] = useState(false)
  const floatingRef = useRef(null)
  // while the slider's knob is dragged: whether the playback was playing before (scrubStart)
  const scrubRef = useRef(false)
  const [openedAt] = useState(() => Date.now()) // the time shown when there is no run
  // what is shown now, for the minute check below (it runs outside a render)
  const viewRef = useRef(null)
  useEffect(() => {
    viewRef.current = { data, shownId, time, followLatest }
  })

  // Load the data when the page opens
  useEffect(() => {
    let cancelled = false // true if the user leaves before the data arrives

    getCurrentTraffic()
      .then((result) => {
        if (cancelled) return
        setData(result)
        // a live run opens on the live clock's moment, before the scene has loaded
        if (result.live && result.run?.status !== 'failed') {
          const target = liveTarget(result)
          setShownId(targetId(result, target))
          setTime(target.seconds)
        }
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
  // Once a live run has been shown, the minute check keeps running even if the page falls back
  // to the sample run, so it returns to live by itself when the loop publishes again
  const [liveSeen, setLiveSeen] = useState(false)
  useEffect(() => {
    if (live) setLiveSeen(true)
  }, [live])
  // checks in a row that found no live run while a live run was shown (see below)
  const missesRef = useRef(0)
  // Live: the real time, read every second, for which timeline bars the live clock has reached
  // and how far the slider can go (the live moment moves on every second)
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    if (!live) return
    const timer = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [live])
  useEffect(() => {
    if (!liveSeen) return
    const timer = setInterval(() => {
      getCurrentTraffic()
        .then((result) => {
          const view = viewRef.current ?? {}
          const current = view.data
          // live/run.json is missing for a moment while a new run moves in (a restart, 03:00):
          // one check without it is not a reason to leave live. Keep what is shown, and switch
          // to the sample only after MAX_LIVE_MISSES checks in a row without a live run.
          if (current?.source === 'live' && result.source !== 'live') {
            missesRef.current += 1
            if (missesRef.current < MAX_LIVE_MISSES) return
          } else {
            missesRef.current = 0
          }
          const changed =
            result.live?.version !== current?.live?.version ||
            result.live?.state !== current?.live?.state ||
            result.live?.stale !== current?.live?.stale ||
            result.source !== current?.source
          if (!changed) return
          setData(result)
          // Following: the clock's moment may now be in the previous run (a new chain that
          // starts after it, at 03:00), so pick the run in the same update
          if (view.followLatest && result.live && result.run?.status !== 'failed') {
            const target = liveTarget(result)
            setShownId(targetId(result, target))
            if (target.inPrevious !== (view.shownId !== null)) {
              setTime(target.seconds)
              setJumpTo({ time: target.seconds })
            }
            return
          }
          // Watching an earlier moment: stay on it. At 03:00 (or a restart) the newest run
          // becomes the previous one, so the moment is looked up again in the new runs. Gone
          // (older than 24 hours): follow the live clock again.
          if (view.followLatest || !current?.run || !result.live) return
          const shownRun = runById(current, view.shownId) ?? current
          const moment = Date.parse(shownRun.run.start) + view.time * 1000
          const place = [result, ...olderRuns(result)].find((runView) =>
            runView?.intervals?.some(
              (item) =>
                Date.parse(item.start) <= moment &&
                moment < Date.parse(item.start) + runView.run.intervalSeconds * 1000,
            ),
          )
          const seconds = place
            ? (moment - Date.parse(place.run.start)) / 1000
            : liveTarget(result).seconds
          setShownId(
            place ? (place === result ? null : place.run.id) : targetId(result, liveTarget(result)),
          )
          setFollowLatest(!place)
          setTime(seconds)
          setJumpTo({ time: seconds })
        })
        .catch(() => {}) // keep showing what is there; the next minute tries again
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [liveSeen])

  // Following: the time shown comes from the live clock itself, twice a second. The scene also
  // reports it, but not while it loads the cars of a new moment (after Latest, or a new run), so
  // without this the time would stand still for a few seconds and then jump
  useEffect(() => {
    if (!live || !followLatest) return
    const timer = setInterval(() => {
      const view = viewRef.current
      const page = view?.data
      if (!page?.live || !page.run || page.run.status === 'failed') return
      const previous = view.shownId !== null ? page.previous : null
      setTime(Math.floor(clockIn(previous, page)))
    }, 500)
    return () => clearInterval(timer)
  }, [live, followLatest])

  // Full screen: the floating timeline sits at the bottom of the scene, and the approaches strip
  // (drawn by the scene) moves up above it, with the timeline button above the strip. The heights
  // they need are measured and given to the CSS as --ft-card-h and --ft-chips-h
  useEffect(() => {
    const scene = sceneRef.current
    if (!scene) return
    if (!fullScreen) {
      scene.style.removeProperty('--ft-card-h')
      scene.style.removeProperty('--ft-chips-h')
      return
    }
    const update = () => {
      const card = floatingRef.current?.querySelector('.card')
      const chips = scene.querySelector('.approach-chips')
      scene.style.setProperty('--ft-card-h', card ? `${card.offsetHeight + 8}px` : '0px')
      scene.style.setProperty('--ft-chips-h', `${chips?.offsetHeight ?? 0}px`)
    }
    update()
    const observer = new ResizeObserver(update)
    if (floatingRef.current) observer.observe(floatingRef.current)
    const timer = setInterval(update, 1000) // the strip appears once the scene has loaded
    return () => {
      observer.disconnect()
      clearInterval(timer)
    }
  }, [fullScreen, floatingOpen, sceneRef])

  // Following while the clock is still in the previous run (the minutes after a new chain is
  // published, before the clock reaches its start): move into the newest run at its start
  useEffect(() => {
    if (!live || !followLatest || shownId === null) return
    const timer = setInterval(() => {
      const target = liveTarget(viewRef.current?.data ?? data)
      if (target.inPrevious) return
      setShownId(null)
      setTime(target.seconds)
    }, 1000)
    return () => clearInterval(timer)
  }, [live, followLatest, shownId, data])

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
  // Live: the timeline covers the last 24 hours: the runs before the newest one (previous, and
  // after restarts the earlier ones) and the newest run, with an empty "Not simulated" bar for
  // each interval none of them covers. The scene, the KPIs and the clock show the run the
  // selected bar is in.
  const previous = data.previous ?? null
  const shown = runById(data, shownId) ?? data
  const { run, hasKpis, isTest, intervals } = shown
  // Live: the timeline stops at the interval the live clock is in. A new interval is published a
  // few minutes before the clock reaches it (the page plays 20 minutes behind), and its bar appears
  // then, so the timeline, the scene, the clock and the KPIs always agree on what "now" is. The
  // interval on screen is always kept, e.g. when the loop is late and the clock waits at the end
  const allBars = withGaps(
    [...olderRuns(data).flatMap((view) => view.timeline), ...data.timeline],
    data.run?.intervalSeconds ?? 900,
  )
  const timeline = (() => {
    if (!live || !liveInfo) return allBars
    const onScreen = intervalsStart(shown, time)
    const reached = Math.max(liveMoment(liveInfo, nowMs), onScreen ?? -Infinity)
    return allBars.filter((bar) => Date.parse(bar.time) <= reached)
  })()
  // Why there is nothing to play, if so: no run yet, or the run failed
  const runProblem = !run
    ? 'No simulated run is available yet.'
    : run.status === 'failed'
      ? `The simulated run failed: ${run.failureReason}`
      : null
  // Why the KPI box is empty, if it is
  const kpiProblem = runProblem ?? (hasKpis ? null : 'KPIs are not available for this run yet.')
  const following = live && followLatest && !runProblem
  // Live: where the scene is now, in seconds from the start of the analysis period. The scene
  // plays the traffic at the time it happened in data time, LIVE_DELAY behind it: by then that
  // moment is always simulated (an interval arrives after it ends, the loop stops 60 s early
  // and takes up to about a minute, and the page looks every minute). It is worked out from
  // the clock, so reloading the page or opening it elsewhere shows the same moment. If the
  // simulation has not got there (the loop is late or stopped), it waits at its end.
  const liveClock = following
    ? () => clockIn(previous && shown === previous ? previous : null, data)
    : null
  // the 15 minutes being played, and the time shown: the clock for live data (set from the clock
  // when the data arrives, so the page opens on the right moment before the scene has loaded),
  // the run's time for a simulated run
  const seconds = time
  const index = runProblem
    ? -1
    : Math.min(intervals.length - 1, Math.floor(seconds / run.intervalSeconds))
  const interval = intervals[index]
  const kpis = interval?.kpis ?? []
  const approaches = interval?.approaches ?? []
  // the run's own time (data time): a live run's traffic is the replay's, not today's clock
  const shownTime = new Date(
    (run ? Date.parse(run.start) : openedAt) + (runProblem ? 0 : seconds * 1000),
  )
  const night = darkness(shownTime, intersection.center)
  const openApproach = approaches.find((a) => a.approach_id === openApproachId)
  const kpiInterval = interval
    ? `${intervalLabel(interval)}${interval.provisional ? ' (provisional)' : ''}`
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
  // of an earlier run switches the scene to that run; the newest bar follows the live clock. A
  // "Not simulated" bar is in no run: nothing happens.
  function selectBar(barTime) {
    // a click on the bar already selected opens its interval as a time slider (the newest bar
    // also goes back to following the live clock)
    const clicked = barTime ?? timeline[timeline.length - 1]?.time // null: the newest bar shown
    const again = clicked !== undefined && clicked === interval?.start
    if (again) setZoomed(true)
    if (again && barTime !== null) return
    const owner =
      barTime === null
        ? data
        : [...olderRuns(data), data].find((view) => view.timeline.some((b) => b.time === barTime))
    if (!owner) return
    const target =
      barTime === null
        ? data.intervals.length - 1
        : owner.timeline.findIndex((b) => b.time === barTime)
    if (target < 0) return
    const follow = barTime === null && live ? liveTarget(data) : null
    const seconds = follow ? follow.seconds : target * owner.run.intervalSeconds
    setShownId(follow ? targetId(data, follow) : owner === data ? null : owner.run.id)
    setFollowLatest(barTime === null)
    // a first click only selects its interval: a second click, or "Zoom into … ›", opens it as a
    // time slider, so the 24-hour timeline can still be clicked through. Following the live
    // clock never pauses
    if (barTime === null) setPaused(false)
    setTime(seconds)
    setJumpTo({ time: seconds })
  }

  // PBI 15: the moment shown, in seconds from the start of the interval on screen, and how far
  // into it the slider may go: the live clock and the end of what has been simulated, or the
  // whole interval in a simulated run
  const intervalSeconds = run?.intervalSeconds ?? 900
  const intervalOffset = index >= 0 ? index * intervalSeconds : 0
  const reachable = (() => {
    if (!live || !liveInfo || !run) return intervalSeconds
    const clockSeconds = (liveMoment(liveInfo, nowMs) - Date.parse(run.start)) / 1000
    const simulated =
      shown === data
        ? (liveInfo.simulatedUntilSeconds ?? 0) - run.analysisStartSeconds
        : intervals.length * intervalSeconds
    return Math.max(0, Math.min(clockSeconds, simulated) - intervalOffset)
  })()

  // Go to a second of the interval on screen; this stops following the live clock, except at
  // "Now" (the end of an interval still happening): that is the live moment, so it follows
  // again, as Latest does
  function seek(secondsInInterval) {
    const atNow = live && reachable < intervalSeconds && secondsInInterval >= Math.floor(reachable) - 1
    if (atNow) {
      selectBar(null)
      return
    }
    const seconds = intervalOffset + secondsInInterval
    const shownEnd = intervals.length * intervalSeconds
    // past the start or the end of the run shown: on into the run before or after it
    if (seconds < 0 && goBackToPreviousRun(seconds)) return
    if (seconds >= shownEnd && goOnInNextRun(seconds, true)) return
    const kept = Math.max(0, Math.min(seconds, shownEnd - 1))
    setFollowLatest(false)
    setTime(kept)
    setJumpTo({ time: kept })
  }

  // Going back past the start of the run shown: the same moment in the run before it, or its last
  // second after a "Not simulated" gap. Returns false when there is no run before
  function goBackToPreviousRun(seconds) {
    const runs = [...olderRuns(data), data]
    const position = runs.indexOf(shown)
    if (position <= 0) return false
    const before = runs[position - 1]
    const beforeEnd = before.intervals.length * before.run.intervalSeconds
    const moment = Date.parse(shown.run.start) + seconds * 1000
    const offset = Math.min(Math.max(0, (moment - Date.parse(before.run.start)) / 1000), beforeEnd - 1)
    setShownId(before.run.id)
    setFollowLatest(false)
    setTime(offset)
    setJumpTo({ time: offset })
    return true
  }

  // While the knob is dragged, the playback holds still, so the scene shows the moment under the
  // knob, going backward as well as forward; it plays on when let go if it was playing
  function scrubStart() {
    scrubRef.current = !paused
    if (!paused) setPaused(true)
  }
  function scrubEnd() {
    if (scrubRef.current) setPaused(false)
    scrubRef.current = false
  }

  // Dragging the slider: go to the moment (ms) in whichever run has it, across intervals and runs.
  // In a "Not simulated" gap, the run on the side the drag is heading to (direction 1 or -1):
  // the next run's start, or the last second of the run before. Past "Now", follow live
  function dragTo(ms, direction) {
    const runs = [...olderRuns(data), data]
    const spans = runs.map((view) => {
      const begin = Date.parse(view.run.start)
      return { view, begin, end: begin + view.intervals.length * view.run.intervalSeconds * 1000 }
    })
    const newest = spans[spans.length - 1]
    if (live && liveInfo) {
      const simulated = (liveInfo.simulatedUntilSeconds ?? 0) - newest.view.run.analysisStartSeconds
      const reachableMs = Math.min(liveMoment(liveInfo), newest.begin + simulated * 1000)
      if (ms >= reachableMs - 1000) {
        selectBar(null)
        return
      }
    }
    let place = spans.find((span) => span.begin <= ms && ms < span.end)
    let moment = ms
    if (!place) {
      const later = direction > 0 ? spans.find((span) => span.begin > ms) : null
      if (later) {
        place = later
        moment = later.begin
      } else if (direction > 0) {
        // past the end of the last run (a simulated run): stay on its last second
        place = newest
        moment = newest.end - 1000
      } else {
        place = [...spans].reverse().find((span) => span.end <= ms) ?? spans[0]
        moment = Math.min(Math.max(ms, place.begin), place.end - 1000)
      }
    }
    const seconds = Math.floor((moment - place.begin) / 1000)
    setShownId(place.view === data ? null : place.view.run.id)
    setFollowLatest(false)
    setTime(seconds)
    setJumpTo({ time: seconds })
  }

  // ‹ and › next to the slider's time: the interval before or after on the timeline that has a run
  // ("Not simulated" gaps are skipped); the newest one follows the live clock
  const barsWithRun = timeline.filter((bar) =>
    [...olderRuns(data), data].some((view) => view.timeline.some((b) => b.time === bar.time)),
  )
  const barIndex = barsWithRun.findIndex((bar) => bar.time === interval?.start)
  const stepTo = (bar) =>
    bar ? () => selectBar(bar === barsWithRun[barsWithRun.length - 1] ? null : bar.time) : null

  // Playing an earlier run past its last interval shown (where the next run starts, or the run's
  // end) goes on in the next run: at the same moment if the runs meet, or at the next run's start
  // after a "Not simulated" gap. Returns false when there is no next run to go on in (the newest
  // run stops at the end of what has been simulated, as before)
  function goOnInNextRun(seconds, keepPaused = false) {
    const runs = [...olderRuns(data), data]
    const position = runs.indexOf(shown)
    if (!live || following || position < 0 || position === runs.length - 1) return false
    const next = runs[position + 1]
    const moment = Date.parse(shown.run.start) + seconds * 1000
    const offset = Math.max(0, (moment - Date.parse(next.run.start)) / 1000)
    setShownId(next === data ? null : next.run.id)
    if (!keepPaused) setPaused(false)
    setTime(offset)
    setJumpTo({ time: offset })
    return true
  }

  // The time the scene is at, once a second
  function sceneTime(seconds) {
    const shownEnd = intervals.length * (run?.intervalSeconds ?? 900)
    if (!paused && seconds >= shownEnd && goOnInNextRun(seconds)) return
    setTime(seconds)
  }

  // The scene reached the end of its run: go on in the next run, or pause there
  function sceneEnd() {
    const shownEnd = intervals.length * (run?.intervalSeconds ?? 900)
    if (!goOnInNextRun(shownEnd)) setPaused(true)
  }

  // Pause holds the moment shown (while live, this leaves the live clock: the view becomes
  // historical); Play continues from it at normal speed
  function togglePlay() {
    if (paused) {
      setPaused(false)
      return
    }
    setFollowLatest(false)
    setPaused(true)
    setJumpTo({ time })
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

  // The timeline under the scene: the 24 hours, or one interval as a time slider (PBI 15). In
  // full screen it can be opened over the scene (floating), so the engineer can still move
  // through time
  const timelineBlock = (floating = false) =>
    zoomed && interval ? (
      <IntervalSlider
        start={interval.start}
        length={intervalSeconds}
        seconds={time - intervalOffset}
        reachable={reachable}
        onSeek={seek}
        paused={paused}
        onTogglePlay={togglePlay}
        onBack={() => setZoomed(false)}
        following={following}
        live={live}
        onLatest={() => selectBar(null)}
        onScrubStart={scrubStart}
        onScrubEnd={scrubEnd}
        onDragTo={dragTo}
        onPrevious={barIndex > 0 ? stepTo(barsWithRun[barIndex - 1]) : null}
        onNext={barIndex >= 0 ? stepTo(barsWithRun[barIndex + 1]) : null}
        className={floating ? 'card-floating' : ''}
      />
    ) : (
      <HistoricalTimeline
        title="Traffic Timeline"
        bars={timeline}
        value={interval?.start ?? null}
        onChange={selectBar}
        live={live}
        following={following}
        emptyMessage={runProblem}
        className={floating ? 'card-floating' : ''}
      >
        {interval && (
          <>
            <Button size="sm" variant="secondary" onClick={togglePlay}>
              <PlayPauseIcon paused={paused} />
              {paused ? 'Play' : 'Pause'}
            </Button>
            <Button size="sm" variant="secondary" onClick={() => setZoomed(true)}>
              Zoom into {intervalLabel(interval)} ›
            </Button>
          </>
        )}
      </HistoricalTimeline>
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
              <EmptyState title="No detector data">
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
                      No detector data for {intervalLabel(interval)}: the cars are not shown.
                    </span>
                  ) : null
                }
              >
                <TrafficScene3D
                  scenario={shown.scenario}
                  runVersion={liveInfo?.version}
                  startAt={time}
                  clock={liveClock}
                  hiddenRanges={hiddenRanges}
                  intersectionId={intersection.id}
                  onTimeChange={sceneTime}
                  jumpTo={jumpTo}
                  center={intersection.center}
                  bounds={intersection.bounds}
                  night={night}
                  approaches={approaches}
                  openApproachId={openApproachId}
                  onApproachChange={setOpenApproachId}
                  onError={setSimError}
                  paused={paused}
                  stopAtEnd
                  onEnd={sceneEnd}
                />
              </SimulationViewport>
            </div>

            {fullScreen && (
              <div
                ref={floatingRef}
                className={`current-traffic-floating-timeline${details ? ' beside-side' : ''}`}
              >
                <Button
                  variant="secondary"
                  size="sm"
                  className="current-traffic-floating-toggle"
                  aria-expanded={floatingOpen}
                  onClick={() => setFloatingOpen((open) => !open)}
                >
                  <svg
                    className={`current-traffic-chevron${floatingOpen ? ' open' : ''}`}
                    viewBox="0 0 16 16"
                    width="14"
                    height="14"
                    aria-hidden="true"
                  >
                    <path d="M4 10l4-4 4 4" fill="none" stroke="currentColor" strokeWidth="2" />
                  </svg>
                  {floatingOpen ? 'Hide timeline' : 'Traffic timeline'}
                </Button>
                {/* the room the approaches strip takes, between the button and the timeline */}
                <div className="current-traffic-floating-gap" aria-hidden="true" />
                {floatingOpen && timelineBlock(true)}
              </div>
            )}
          </div>

          {!fullScreen && timelineBlock()}
        </div>
      </div>
    </div>
  )
}

// How often a live run is checked for a new interval
const POLL_MS = 60 * 1000
// Checks in a row without a live run before a page showing live falls back to the sample run
const MAX_LIVE_MISSES = 3
// How far the live scene plays behind the data's own time (see liveClock)
const LIVE_DELAY_MS = 20 * 60 * 1000

// Live: the moment the live clock shows, in data time (ms). It plays the traffic LIVE_DELAY_MS
// after it happened
function liveMoment(liveInfo, now = Date.now()) {
  return now - liveInfo.clockOffsetMs - LIVE_DELAY_MS
}

// The start (ms) of the interval a run view plays at the given seconds, or null without one
function intervalsStart(view, seconds) {
  const intervals = view?.intervals ?? []
  if (!intervals.length || !view.run?.intervalSeconds) return null
  const index = Math.min(intervals.length - 1, Math.floor(seconds / view.run.intervalSeconds))
  return Date.parse(intervals[Math.max(0, index)].start)
}

// Live: where the live clock is in one run, in seconds from the start of its analysis period:
// the newest run (previous null), waiting at the end of what has been simulated, or the
// previous run (previous given), up to its last interval
function clockIn(previous, page) {
  const view = previous ?? page
  const end = previous
    ? previous.intervals.length * previous.run.intervalSeconds
    : (page.live.simulatedUntilSeconds ?? 0) - page.run.analysisStartSeconds
  const seconds = (liveMoment(page.live) - Date.parse(view.run.start)) / 1000
  return Math.max(0, Math.min(seconds, end))
}

// Live: the runs before the newest one, oldest first: the earlier ones (after restarts), then
// the previous one
function olderRuns(page) {
  return [...(page?.earlier ?? []), ...(page?.previous ? [page.previous] : [])]
}

// Live: the earlier run with this run ID, or null (null is the newest run)
function runById(page, id) {
  return id === null ? null : (olderRuns(page).find((view) => view.run.id === id) ?? null)
}

// Live: the shownId for a liveTarget result: the previous run's ID, or null for the newest run
function targetId(page, target) {
  return target.inPrevious ? page.previous.run.id : null
}

// Live: the run the live clock is in, and where. It is the newest run, except in the minutes
// after a new chain is published, when the clock has not reached its start yet (it plays
// 20 minutes behind): then it is the previous run, which goes on to that start
function liveTarget(page) {
  const previous = page.previous
  const inPrevious = Boolean(
    previous?.intervals?.length && liveMoment(page.live) < Date.parse(page.run.start),
  )
  return { inPrevious, seconds: clockIn(inPrevious ? previous : null, page) }
}
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
    <Badge variant="warning">Historical</Badge>
  )
}

// Times on this page are data times at the intersection: Riyadh time, whatever the browser's zone
const CLOCK = { hour: '2-digit', minute: '2-digit', timeZone: RIYADH_TIME_ZONE }

// e.g. "21:30", or "unknown" without a time
function formatTime(iso) {
  if (!iso) return 'unknown'
  return new Date(iso).toLocaleTimeString('en-GB', CLOCK)
}

// e.g. "Sat 10 Oct, 21:30"
function formatLabel(date) {
  const day = date
    .toLocaleDateString('en-GB', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      timeZone: RIYADH_TIME_ZONE,
    })
    .replace(',', '')
  const time = date.toLocaleTimeString('en-GB', CLOCK)
  return `${day}, ${time}`
}

// The 15 minutes the KPIs cover, e.g. "08:15–08:30"
function intervalLabel({ start, end }) {
  const time = (iso) => new Date(iso).toLocaleTimeString('en-GB', CLOCK)
  return `${time(start)}–${time(end)}`
}

export default CurrentTraffic
