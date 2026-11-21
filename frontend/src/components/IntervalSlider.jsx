import Badge from './Badge'
import Button from './Button'
import Card from './Card'
import { RIYADH_TIME_ZONE } from '../utils/riyadhTime'
import './IntervalSlider.css'

// One 15-minute interval as a time slider, to go to any second of it: the timeline "zoomed in".
// Current Traffic shows it in place of the 24-hour timeline when an interval is opened.
//
//   start          when the interval starts, e.g. '2026-08-22T02:15:00+03:00'
//   seconds        the moment shown, in seconds from the interval start (0 to length)
//   length         the interval's length in seconds (900 unless you say otherwise)
//   reachable      how far into the interval can be shown, in seconds: the slider stops there
//                  (the live clock, or the end of what has been simulated). The whole interval
//                  unless you say otherwise. Short of the end (an interval still happening),
//                  the track stops there, marked "Now"; the rest of the scale is faded
//   onSeek         called with the new seconds when the slider is moved
//   paused         true while the playback is paused
//   onTogglePlay   called when Pause / Play is pressed
//   onBack         called by "All 24 hours": back to the 24-hour timeline
//   following      true while the page follows the live clock (the badge says Live)
//   live           false for a simulated run: no Live / Historical badge and no Latest button
//   onLatest       called by Latest, to follow the live clock again
//
// The slider moves in whole seconds. Keys: arrows 1 s, Shift + arrows 10 s, Page Up / Page Down
// 1 minute, Home / End the start and the furthest reachable second.
function IntervalSlider({
  start,
  seconds,
  length = 900,
  reachable = length,
  onSeek,
  paused,
  onTogglePlay,
  onBack,
  following = false,
  live = true,
  onLatest,
}) {
  const startMs = Date.parse(start)
  const limit = Math.max(0, Math.min(length, Math.floor(reachable)))
  const value = Math.max(0, Math.min(limit, Math.floor(seconds)))
  const minutes = Math.round(length / 60)
  // the interval is still happening (live): the slider ends at "now", and the rest of the
  // 15 minutes is only a faded scale, with no track, so it does not look reachable. A time
  // label that close to "Now" is left out, so the two never overlap
  const unfinished = limit < length

  function seek(next) {
    onSeek(Math.max(0, Math.min(limit, Math.round(next))))
  }

  // the slider's own keys move 1 s; these add 10 s, 1 minute and the reachable end
  function onKeyDown(event) {
    const steps = {
      ArrowLeft: event.shiftKey ? -10 : null,
      ArrowDown: event.shiftKey ? -10 : null,
      ArrowRight: event.shiftKey ? 10 : null,
      ArrowUp: event.shiftKey ? 10 : null,
      PageDown: -60,
      PageUp: 60,
    }
    if (event.key === 'End') {
      event.preventDefault()
      seek(limit)
    } else if (steps[event.key]) {
      event.preventDefault()
      seek(value + steps[event.key])
    }
  }

  return (
    <Card
      title="Traffic Timeline"
      action={
        <Button size="sm" variant="secondary" onClick={onBack}>
          ← All 24 hours
        </Button>
      }
    >
      <div className="interval-slider-controls">
        <Button
          size="sm"
          variant="secondary"
          onClick={onTogglePlay}
          aria-label={paused ? 'Play' : 'Pause'}
        >
          {paused ? '▶ Play' : '❚❚ Pause'}
        </Button>
        <span className="interval-slider-time">{clock(startMs + value * 1000, true)}</span>
        <span className="interval-slider-range">
          {clock(startMs, false)}–{unfinished ? 'now' : clock(startMs + length * 1000, false)}
        </span>
      </div>

      <div
        className={`interval-slider-plot ${unfinished ? 'unfinished' : ''}`}
        style={{ '--reachable': `${(limit / length) * 100}%` }}
      >
        <input
          type="range"
          className="interval-slider-input"
          min={0}
          max={length}
          step={1}
          value={value}
          aria-label="Moment shown"
          aria-valuetext={clock(startMs + value * 1000, true)}
          onChange={(event) => seek(Number(event.target.value))}
          onKeyDown={onKeyDown}
        />
        {/* minute ticks, with a time under every 5 minutes */}
        <div className="interval-slider-axis" aria-hidden="true">
          {Array.from({ length: minutes + 1 }, (_, minute) => (
            <span
              key={minute}
              className={`interval-slider-tick ${minute % 5 === 0 ? 'major' : ''} ${
                minute * 60 > limit ? 'future' : ''
              }`}
              style={{ left: `${(minute / minutes) * 100}%` }}
            >
              {minute % 5 === 0 &&
                !(unfinished && Math.abs(minute * 60 - limit) < 75) &&
                clock(startMs + minute * 60000, false)}
            </span>
          ))}
          {unfinished && (
            <span className="interval-slider-now" style={{ left: 'var(--reachable)' }}>
              Now
            </span>
          )}
        </div>
      </div>

      <div className="interval-slider-footer">
        <p className="interval-slider-readout">
          {live &&
            (following ? (
              <Badge variant="success">Live</Badge>
            ) : (
              <Badge variant="warning">Historical</Badge>
            ))}
          <span>{day(startMs)}</span>
        </p>
        {live && !following && (
          <Button variant="secondary" size="sm" onClick={onLatest}>
            Latest
          </Button>
        )}
      </div>
    </Card>
  )
}

// e.g. "02:17:34" (with seconds) or "02:15"
function clock(ms, withSeconds) {
  return new Date(ms).toLocaleTimeString('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
    timeZone: RIYADH_TIME_ZONE,
  })
}

// e.g. "Sat 22 Aug"
function day(ms) {
  return new Date(ms)
    .toLocaleDateString('en-GB', {
      weekday: 'short',
      day: 'numeric',
      month: 'short',
      timeZone: RIYADH_TIME_ZONE,
    })
    .replace(',', '')
}

export default IntervalSlider
