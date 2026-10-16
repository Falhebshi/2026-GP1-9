import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../components/Button'
import Card from '../components/Card'
import HistoricalTimeline from '../components/HistoricalTimeline'
import NetworkMap from '../components/NetworkMap'
import SegmentedControl from '../components/SegmentedControl'
import Select from '../components/Select'
import { sampleTimelineBars } from '../services/currentTrafficData'
import { loadSegments, NETWORK_BOUNDS, NETWORK_INTERSECTIONS } from '../services/networkData'
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

// the last 7 days, today first ('' means today, so the timeline follows live data)
function dayOptions(now) {
  const options = [{ value: '', label: 'Today' }]
  for (let back = 1; back < 7; back++) {
    const d = new Date(now - back * DAY)
    const value = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
    const label = d.toLocaleDateString('en-GB', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
    })
    options.push({ value, label })
  }
  return options
}

// ours first, then the ones without a simulation yet (shown greyed out)
const INTERSECTION_OPTIONS = [...NETWORK_INTERSECTIONS]
  .sort((a, b) => Boolean(b.simulation) - Boolean(a.simulation))
  .map((i) => ({
    value: i.id,
    label: `${i.area} · ${i.name}${i.simulation ? '' : ' (not available yet)'}`,
    disabled: !i.simulation,
  }))

function NetworkOverview() {
  const navigate = useNavigate()
  const [now] = useState(() => Date.now())
  const [view, setView] = useState('segments')
  const [intersectionId, setIntersectionId] = useState('')
  const [day, setDay] = useState('') // '' = today
  const [time, setTime] = useState(null) // null = latest
  const [segments, setSegments] = useState(null)
  const timelineRef = useRef(null)
  const [timelineHeight, setTimelineHeight] = useState(0)

  // 24 hours of bars: the last 24 hours today, or the whole of a past day
  const bars = useMemo(
    () =>
      day ? sampleTimelineBars(new Date(`${day}T23:45:00`).getTime()) : sampleTimelineBars(now),
    [day, now],
  )
  const shown = time ? new Date(time) : new Date(bars.at(-1).time)

  useEffect(() => {
    let cancelled = false
    loadSegments(time).then((data) => {
      if (!cancelled) setSegments(data)
    })
    return () => {
      cancelled = true
    }
  }, [time])

  // keep the map's own buttons above the timeline card
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => setTimelineHeight(entry.contentRect.height))
    observer.observe(timelineRef.current)
    return () => observer.disconnect()
  }, [])

  function changeDay(value) {
    setDay(value)
    // keep the same hour on the new day
    if (value) setTime(`${value}T${pad(shown.getHours())}:00:00`)
    else setTime(null)
  }

  // the most recent bar that starts at this hour
  function goToHour(hour) {
    const bar = [...bars].reverse().find((b) => {
      const d = new Date(b.time)
      return d.getHours() === hour && d.getMinutes() === 0
    })
    if (bar) setTime(bar === bars.at(-1) && !day ? null : bar.time)
  }

  const hourOptions = []
  for (let h = 0; h < 24; h++) {
    if (bars.some((b) => new Date(b.time).getHours() === h))
      hourOptions.push({ value: String(h), label: hourLabel(h) })
  }
  const activePeak = PEAKS.find((p) => shown.getHours() >= p.from && shown.getHours() < p.to)

  return (
    <div className="network-overview" style={{ '--map-bottom-inset': `${timelineHeight + 32}px` }}>
      <NetworkMap
        bounds={NETWORK_BOUNDS}
        segments={segments}
        view={view}
        intersections={NETWORK_INTERSECTIONS}
        selectedId={intersectionId}
        onSelect={setIntersectionId}
        onArrive={(id) => {
          // after zooming in, open the intersection's own page
          const target = NETWORK_INTERSECTIONS.find((i) => i.id === id)?.simulation
          if (target) navigate(target)
        }}
      />

      <div className="network-overview-side">
        <Card floating className="network-overview-title">
          <h1>Network Traffic Overview</h1>
        </Card>

        <Card floating title="Intersections by area" className="network-overview-picker">
          <Select
            ariaLabel="Intersection"
            placeholder="Select intersection"
            options={INTERSECTION_OPTIONS}
            value={intersectionId}
            onChange={setIntersectionId}
          />
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
      </div>

      <div className="network-overview-timeline" ref={timelineRef}>
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
            options={dayOptions(now)}
            value={day}
            onChange={changeDay}
          />
          <Select
            ariaLabel="Hour"
            size="sm"
            options={hourOptions}
            value={String(shown.getHours())}
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
      </div>
    </div>
  )
}

export default NetworkOverview
