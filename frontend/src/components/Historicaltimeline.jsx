import { useState } from 'react'
import Badge from './Badge'
import Button from './Button'
import Card from './Card'
import EmptyState from './EmptyState'
import './HistoricalTimeline.css'

// The last 24 hours of congestion as a row of bars, with a slider for going
// back to an earlier time.
//
//   bars             the bars, OLDEST FIRST, one per time step:
//                      time    when the step starts, e.g. '2026-10-10T07:15:00'
//                      value   congestion from 0 (free flow) to 1 (worst).
//                              Sets the HEIGHT. Leave it out for "no data".
//                      level   'low', 'moderate' or 'high'. Sets the COLOR.
//   value            the time of the selected bar, or null for "the latest"
//   onChange         function called with the new time (or null for latest)
//                    when the user picks a bar, drags the slider or clicks
//                    the Latest button
//   intervalMinutes  how long one bar lasts (15 unless you say otherwise)
//   title            heading of the card
//   error            text shown instead of the bars when the data failed to load
//
// Anything you put between <HistoricalTimeline> and </HistoricalTimeline> is
// shown above the bars, e.g. the peak-period buttons on Network Overview.
//
// Built for real time: the component never assumes the bars run from
// midnight to midnight. It draws whatever list it is given and reads the
// labels from each bar's own time. When a new 15 minutes arrives, the page
// passes a new list (oldest bar dropped, newest added) and nothing else
// has to change:
//   - while value is null, the slider stays on the newest bar
//   - while value is a time, the slider stays on that moment as it slides left
function HistoricalTimeline({
  bars = [],
  value = null,
  onChange,
  intervalMinutes = 15,
  title = 'Historical Timeline',
  error,
  className = '',
  children,
}) {
  // Which bar the mouse is over (for the tooltip). null means none.
  const [hoverIndex, setHoverIndex] = useState(null)

  // Turn each bar's time into a Date once, so the code below can read
  // hours and minutes from it
  const points = bars.map((bar) => ({ ...bar, date: new Date(bar.time) }))
  const lastIndex = points.length - 1

  const selectedIndex = findSelectedIndex(points, value)
  const selected = points[selectedIndex]
  const isLatest = selectedIndex === lastIndex
  const hovered = hoverIndex === null ? null : points[hoverIndex]

  function select(index) {
    // Picking the newest bar means "latest", so the slider keeps following
    // new bars as they arrive
    onChange(index === lastIndex ? null : points[index].time)
  }

  const legend = (
    <div className="timeline-legend">
      <span>Low</span>
      <span className="timeline-swatch timeline-level-low" />
      <span className="timeline-swatch timeline-level-moderate" />
      <span className="timeline-swatch timeline-level-high" />
      <span>High congestion</span>
    </div>
  )

  const hasBars = !error && points.length > 0

  return (
    <Card title={title} action={hasBars ? legend : null} className={className}>
      {children && <div className="timeline-controls">{children}</div>}

      {error && (
        <EmptyState variant="error" title="Timeline unavailable">
          {error}
        </EmptyState>
      )}

      {!error && points.length === 0 && (
        <EmptyState>No traffic data is available for the last 24 hours.</EmptyState>
      )}

      {hasBars && (
        <>
          {/* --count tells the CSS how many columns to make */}
          <div className="timeline-plot" style={{ '--count': points.length }}>
            <div
              className="timeline-bars"
              onPointerLeave={() => setHoverIndex(null)}
            >
              {points.map((point, index) => {
                const isMidnight =
                  index > 0 &&
                  point.date.getHours() === 0 &&
                  point.date.getMinutes() === 0

                return (
                  // One column: as tall as the plot, so it is easy to hit
                  // even when its bar is short
                  <div
                    key={point.time}
                    className={[
                      'timeline-column',
                      index === selectedIndex ? 'selected' : '',
                      isMidnight ? 'day-start' : '',
                    ].join(' ')}
                    onPointerEnter={() => setHoverIndex(index)}
                    onClick={() => select(index)}
                  >
                    <div
                      className={`timeline-bar timeline-level-${levelOf(point)}`}
                      style={{ height: barHeight(point) }}
                    />
                  </div>
                )
              })}

              {/* Tooltip for the bar under the mouse */}
              {hovered && (
                <div
                  className="timeline-tooltip"
                  style={{
                    '--x': `${((hoverIndex + 0.5) / points.length) * 100}%`,
                    '--y': barHeight(hovered),
                  }}
                >
                  <strong>{formatRange(hovered.date, intervalMinutes)}</strong>
                  <span className="timeline-tooltip-level">
                    <span
                      className={`timeline-swatch timeline-level-${levelOf(hovered)}`}
                    />
                    {levelLabel(hovered)}
                  </span>
                </div>
              )}
            </div>

            {/* The slider. A real <input type="range"> gives dragging and
                keyboard control (arrow keys, Home, End) for free. */}
            <input
              type="range"
              className="timeline-slider"
              min={0}
              max={lastIndex}
              step={1}
              value={selectedIndex}
              aria-label="Time shown"
              aria-valuetext={describe(selected, intervalMinutes)}
              onChange={(event) => select(Number(event.target.value))}
            />

            {/* Hour labels: one under every bar that starts on the hour */}
            <div className="timeline-axis" aria-hidden="true">
              {points.map((point, index) => {
                if (point.date.getMinutes() !== 0) return null
                const hour = point.date.getHours()

                return (
                  <span
                    key={point.time}
                    className={[
                      'timeline-tick',
                      hour % 2 === 0 ? 'every-2' : '',
                      hour % 4 === 0 ? 'every-4' : '',
                      hour === 0 ? 'day-start' : '',
                    ].join(' ')}
                    style={{ gridColumn: index + 1 }}
                  >
                    {/* Midnight shows the day instead, so it is clear where
                        yesterday ends and today begins */}
                    {hour === 0 ? formatDay(point.date) : formatTime(point.date)}
                  </span>
                )
              })}
            </div>
          </div>

          {/* What is being shown, and the way back to the latest time */}
          <div className="timeline-footer">
            <p className="timeline-readout">
              {isLatest ? (
                <Badge variant="success">Live</Badge>
              ) : (
                <Badge variant="warning">Historical</Badge>
              )}
              <span>{describe(selected, intervalMinutes)}</span>
            </p>

            {!isLatest && (
              <Button variant="secondary" size="sm" onClick={() => onChange(null)}>
                Latest
              </Button>
            )}
          </div>
        </>
      )}
    </Card>
  )
}

// ---- Helpers ---------------------------------------------------------------

const LEVEL_LABELS = {
  low: 'Low congestion',
  moderate: 'Moderate congestion',
  high: 'High congestion',
}

// Position of the selected bar. null means the newest one. If the exact time
// is not in the list (it may have dropped off the left edge), use the bar
// closest to it.
function findSelectedIndex(points, value) {
  if (value === null || value === undefined) return points.length - 1

  const target = new Date(value).getTime()
  let closest = 0

  points.forEach((point, index) => {
    const distance = Math.abs(point.date.getTime() - target)
    const closestDistance = Math.abs(points[closest].date.getTime() - target)
    if (distance < closestDistance) closest = index
  })

  return closest
}

function hasValue(point) {
  return typeof point.value === 'number'
}

// Which color class a bar gets. Unknown or missing levels are drawn grey.
function levelOf(point) {
  return hasValue(point) && LEVEL_LABELS[point.level] ? point.level : 'none'
}

function levelLabel(point) {
  return hasValue(point) ? (LEVEL_LABELS[point.level] ?? 'Not classified') : 'No data'
}

// 0 to 1 becomes "0%" to "100%". A bar with no data becomes a short stub.
function barHeight(point) {
  if (!hasValue(point)) return '4px'
  const clamped = Math.min(Math.max(point.value, 0), 1)
  return `${Math.round(clamped * 100)}%`
}

// "07:15"
function formatTime(date) {
  return date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
}

// "Sat 10"
function formatDay(date) {
  return date
    .toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' })
    .replace(',', '')
}

// "07:15 – 07:30"
function formatRange(date, intervalMinutes) {
  const end = new Date(date.getTime() + intervalMinutes * 60 * 1000)
  return `${formatTime(date)} – ${formatTime(end)}`
}

// "Sat 10 Oct, 07:15 – 07:30 · High congestion"
function describe(point, intervalMinutes) {
  const day = point.date
    .toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
    .replace(',', '') // some browsers write "Sat, 10 Oct"
  return `${day}, ${formatRange(point.date, intervalMinutes)} · ${levelLabel(point)}`
}

export default HistoricalTimeline