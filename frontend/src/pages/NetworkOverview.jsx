import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import HistoricalTimeline from '../components/HistoricalTimeline'
import NetworkMap from '../components/NetworkMap'
import Notice from '../components/Notice'
import SegmentedControl from '../components/SegmentedControl'
import Select from '../components/Select'
import {
  getAvailableDays,
  getNetwork,
  getNetworkSource,
  getNetworkTimeline,
  getOpeningTime,
  getSegments,
} from '../services/networkService'
import { RIYADH_TIME_ZONE, riyadhParts, riyadhTime } from '../utils/riyadhTime'
import './NetworkOverview.css'

// Network Traffic Overview: the city map with road congestion, a list of intersections by
// district, and the historical timeline with past date, time and peak periods.

const VIEW_OPTIONS = [
  { value: 'segments', label: 'Segments' },
  { value: 'heatmap', label: 'Heatmap' },
]

const PEAKS = [
  { id: 'morning', label: 'Morning peak', from: 7, to: 9 },
  { id: 'offpeak', label: 'Off-peak', from: 10, to: 15 },
  { id: 'evening', label: 'Evening peak', from: 16, to: 18 },
]

const DAY = 24 * 60 * 60 * 1000
const pad = (n) => String(n).padStart(2, '0')
const hourLabel = (h) => `${pad(h)}:00`
// "17:15" of a moment, in Riyadh time
const timeLabel = (ms) => {
  const { hour, minute } = riyadhParts(ms)
  return `${pad(hour)}:${pad(minute)}`
}

// "Sat 14 Nov" of a Riyadh day (YYYY-MM-DD)
const dayLabel = (day) =>
  new Date(riyadhTime(day, 12)).toLocaleDateString('en-GB', {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
    timeZone: RIYADH_TIME_ZONE,
  })

// The days to pick from, newest first. With network data, the days that have it ('' is the
// newest); without, the last 7 days ('' is today, so the timeline follows live data). Days are
// Riyadh days.
function dayOptions(now, availableDays) {
  const today = riyadhParts(now).day
  if (availableDays.length) {
    return [...availableDays].reverse().map((day, i) => ({
      value: i === 0 ? '' : day,
      label: day === today ? 'Today' : dayLabel(day),
    }))
  }
  const options = [{ value: '', label: 'Today' }]
  for (let back = 1; back < 7; back++) {
    const day = riyadhParts(now - back * DAY).day
    options.push({ value: day, label: dayLabel(day) })
  }
  return options
}

// What the map colors mean. Roads and areas without data are left as the basemap shows them.
const LEGEND_ROWS = [
  { level: 'low', label: 'Low' },
  { level: 'moderate', label: 'Moderate' },
  { level: 'high', label: 'High' },
  { level: 'none', label: 'No data' },
]

function CongestionLegend() {
  return (
    <div className="network-legend">
      <span className="network-legend-title">Congestion</span>
      <ul>
        {LEGEND_ROWS.map((row) => (
          <li key={row.level}>
            <span className={`network-legend-swatch network-legend-${row.level}`} />
            <span className="network-legend-label">{row.label}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// ours first, then the ones without a simulation yet (shown greyed out)
function intersectionOptions(intersections) {
  return [...intersections]
    .sort((a, b) => Boolean(b.simulation) - Boolean(a.simulation))
    .map((i) => ({
      value: i.id,
      label: `${i.area} · ${i.name}${i.simulation ? '' : ' (not available yet)'}`,
      disabled: !i.simulation,
    }))
}

function NetworkOverview() {
  const navigate = useNavigate()
  const [now, setNow] = useState(() => Date.now())
  const [view, setView] = useState('segments')
  const [intersectionId, setIntersectionId] = useState('')
  const [day, setDay] = useState('') // '' = today
  const [time, setTime] = useState(null) // null = latest
  const [network, setNetwork] = useState(null) // map area and intersections, once they arrive
  const [error, setError] = useState(null) // the error message, if loading failed
  const [bars, setBars] = useState([])
  const [segments, setSegments] = useState(null)
  // days with network data: [] while the server fills its first interval, null when it is not running
  const [availableDays, setAvailableDays] = useState([])
  const [source, setSource] = useState(null) // 'rcrc' or 'synthetic', from the network server
  const [timelineOpen, setTimelineOpen] = useState(false) // closed, so the map gets the room
  const timelineRef = useRef(null)
  const sideRef = useRef(null)
  const [timelineHeight, setTimelineHeight] = useState(0)
  const [sideWidth, setSideWidth] = useState(0)

  // Load the map area and the intersections once, when the page opens
  useEffect(() => {
    let cancelled = false // true if the user leaves before the data arrives

    getNetwork()
      .then((result) => {
        if (!cancelled) setNetwork(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })

    // with network data that does not reach today, open on the current time of day on the newest day
    getOpeningTime().then((opening) => {
      if (!cancelled && opening) setTime(opening)
    })

    return () => {
      cancelled = true
    }
  }, [])

  // check for new data every minute: the network server adds every completed 15 minutes, and
  // the latest bar and the map follow it
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 60000)
    return () => clearInterval(timer)
  }, [])

  // the days with data, again every minute: the server fills them after it starts, and it can be
  // started or stopped while the page is open
  useEffect(() => {
    let cancelled = false
    getAvailableDays().then((days) => {
      if (!cancelled) setAvailableDays(days)
    })
    getNetworkSource().then((name) => {
      if (!cancelled) setSource(name)
    })
    return () => {
      cancelled = true
    }
  }, [now])

  // 24 hours of bars: the last 24 hours today, or the whole of a past day
  useEffect(() => {
    let cancelled = false
    const end = day ? Date.parse(riyadhTime(day, 23, 45)) : now
    getNetworkTimeline(end)
      .then((result) => {
        if (!cancelled) setBars(result.bars)
      })
      .catch(() => {
        if (!cancelled) setBars([]) // tried again at the next minute
      })
    return () => {
      cancelled = true
    }
  }, [day, now])

  const latest = bars.at(-1)?.time
  const shown = time ? new Date(time) : new Date(latest ?? now)
  const shownHour = riyadhParts(shown.getTime()).hour // the hour in Riyadh

  // the map at the chosen time; for the latest data, again whenever a new bar arrives; and again when
  // the server starts, stops or adds a day
  const liveBar = time ? null : latest
  const dayCount = availableDays === null ? -1 : availableDays.length
  useEffect(() => {
    let cancelled = false
    getSegments(time)
      .then((data) => {
        if (!cancelled) setSegments(data)
      })
      .catch(() => {
        if (!cancelled) setSegments(null) // the plain map until the next try
      })
    return () => {
      cancelled = true
    }
  }, [time, liveBar, dayCount])

  // the size of the floating cards: the map keeps its buttons above the timeline, and fits the
  // study area into the space the cards leave free, so the intersection dots are never under them
  useEffect(() => {
    if (!timelineRef.current || !sideRef.current) return undefined
    const observer = new ResizeObserver(() => {
      setTimelineHeight(timelineRef.current.getBoundingClientRect().height)
      setSideWidth(sideRef.current.getBoundingClientRect().width)
    })
    observer.observe(timelineRef.current)
    observer.observe(sideRef.current)
    return () => observer.disconnect()
  }, [network])

  function changeDay(value) {
    setDay(value)
    // keep the same hour on the new day; '' (the newest day) goes to the latest data
    if (value) setTime(riyadhTime(value, shownHour))
    else setTime(null)
  }

  // the most recent bar that starts at this hour
  function goToHour(hour) {
    const bar = [...bars].reverse().find((b) => {
      const t = riyadhParts(Date.parse(b.time))
      return t.hour === hour && t.minute === 0
    })
    if (bar) setTime(bar === bars.at(-1) && !day ? null : bar.time)
  }

  const hourOptions = []
  for (let h = 0; h < 24; h++) {
    if (bars.some((b) => riyadhParts(Date.parse(b.time)).hour === h))
      hourOptions.push({ value: String(h), label: hourLabel(h) })
  }
  const activePeak = PEAKS.find((p) => shownHour >= p.from && shownHour < p.to)

  if (error) {
    return (
      <EmptyState variant="error" title="Network overview unavailable">
        {error}
      </EmptyState>
    )
  }

  if (!network) {
    return <EmptyState>Loading the network…</EmptyState>
  }

  const { bounds, maxBounds, intersections } = network

  return (
    <div className="network-overview" style={{ '--map-bottom-inset': `${timelineHeight + 32}px` }}>
      <NetworkMap
        bounds={bounds}
        maxBounds={maxBounds}
        segments={segments}
        view={view}
        intersections={intersections}
        selectedId={intersectionId}
        onSelect={setIntersectionId}
        padding={{ top: 80, right: 40, bottom: timelineHeight + 40, left: sideWidth + 40 }}
        onArrive={(id) => {
          // after zooming in, open the intersection's own page
          const target = intersections.find((i) => i.id === id)?.simulation
          if (target) navigate(target)
        }}
      />

      <div className="network-overview-side" ref={sideRef}>
        <Card floating className="network-overview-title">
          <h1>Network Traffic Overview</h1>
        </Card>

        {segments && !segments.hasSpeeds && (
          <Notice variant="info">
            {time
              ? `No congestion data for ${dayLabel(riyadhParts(shown.getTime()).day)}, ${timeLabel(shown.getTime())}.`
              : 'No congestion data has been stored yet.'}
          </Notice>
        )}

        {network.isSample && (
          <Notice variant="warning">
            {availableDays === null
              ? 'Road congestion is not available: the network map server is not running.'
              : !availableDays.length
                ? 'Loading road congestion: the network map server is preparing the last 7 days.'
                : source === 'rcrc'
                  ? 'Modelled data: road congestion is estimated from the traffic counted at one intersection (RCRC), not measured on these roads.'
                  : 'Synthetic data: road congestion is generated from real daily traffic patterns, not measured on these roads.'}
          </Notice>
        )}

        <Card floating title="Intersections by area" className="network-overview-picker">
          {intersections.length ? (
            <Select
              ariaLabel="Intersection"
              placeholder="Select intersection"
              options={intersectionOptions(intersections)}
              value={intersectionId}
              onChange={setIntersectionId}
            />
          ) : (
            <EmptyState>No intersections are available.</EmptyState>
          )}
        </Card>
      </div>

      <div className="network-overview-view">
        <SegmentedControl
          ariaLabel="Map view"
          size="sm"
          options={VIEW_OPTIONS}
          value={view}
          onChange={setView}
        />
        {segments && (
          <Card floating className="network-overview-legend">
            <CongestionLegend />
          </Card>
        )}
      </div>

      <div
        className={`network-overview-timeline${timelineOpen ? '' : ' network-overview-timeline-closed'}`}
        ref={timelineRef}
      >
        <Button
          variant="secondary"
          size="sm"
          className="network-overview-timeline-toggle"
          aria-expanded={timelineOpen}
          onClick={() => setTimelineOpen((open) => !open)}
        >
          <svg
            className="network-overview-chevron"
            viewBox="0 0 16 16"
            width="14"
            height="14"
            aria-hidden="true"
          >
            <path d="M4 10l4-4 4 4" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
          {timelineOpen ? 'Hide timeline' : 'Traffic timeline'}
        </Button>

        {timelineOpen && (
          <HistoricalTimeline
            title="Traffic Timeline"
            bars={bars}
            value={time}
            onChange={(value) => {
              // the Latest button (or the newest bar) goes back to today's live data
              if (value === null) {
                setDay('')
                setTime(null)
              } else setTime(value)
            }}
            className="card-floating"
          >
            <Select
              label="Past time"
              size="sm"
              options={dayOptions(now, availableDays ?? [])}
              value={day}
              onChange={changeDay}
            />
            <Select
              ariaLabel="Hour"
              size="sm"
              options={hourOptions}
              value={String(shownHour)}
              onChange={(h) => goToHour(Number(h))}
            />
            <span className="network-overview-divider" />
            {PEAKS.map((peak) => (
              <Button
                key={peak.id}
                size="sm"
                variant={activePeak === peak ? 'primary' : 'secondary'}
                onClick={() => goToHour(peak.from)}
              >
                {peak.label} · {hourLabel(peak.from)}–{hourLabel(peak.to)}
              </Button>
            ))}
          </HistoricalTimeline>
        )}
      </div>
    </div>
  )
}

export default NetworkOverview
