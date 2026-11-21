import Badge from './Badge'
import Button from './Button'
import Card from './Card'
import PlayPauseIcon from './PlayPauseIcon'
import { useEffect, useRef } from 'react'
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
//   onBack         called by "Back to 24 hours": back to the 24-hour timeline
//   following      true while the page follows the live clock (the badge says Live)
//   live           false for a simulated run: no Live / Historical badge and no Latest button
//   onLatest       called by "Back to live", to follow the live clock again
//   onPrevious     called by ‹ next to the time: the interval before (null: none, it is off)
//   onNext         called by › next to the time: the interval after (null: none, it is off)
//   onScrubStart   called when the bar is pressed, and onScrubEnd when it is let go: the page
//                  holds the playback still meanwhile, so the scene follows the knob both ways
//   onDragTo       called while dragging with the moment (ms) and the direction (1 or -1): the
//                  page finds the interval it is in, before or after this one, across runs
//   className      extra classes for the card, e.g. "card-floating" over the scene in full screen
//
// The slider moves in whole seconds. Keys: arrows 1 s, Shift + arrows 10 s, Page Up / Page Down
// 1 minute, Home / End the start and the furthest reachable second; the keys go on into the
// interval before or after. A drag moves the moment by how far the pointer moves, so it carries
// on into the interval before or after at the same pace.
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
  onPrevious,
  onNext,
  onScrubStart,
  onScrubEnd,
  onDragTo,
  className = '',
}) {
  // A drag moves the moment by how far the pointer moves (the bar's width is the interval's
  // length), not to where the pointer is. So it carries on smoothly into the interval after or
  // before, at the same pace, instead of skipping several when the pointer reaches an end
  const dragRef = useRef(null)
  const startRef = useRef(Date.parse(start))
  useEffect(() => {
    startRef.current = Date.parse(start)
  }, [start])
  const startMs = Date.parse(start)
  const limit = Math.max(0, Math.min(length, Math.floor(reachable)))
  const value = Math.max(0, Math.min(limit, Math.floor(seconds)))
  const minutes = Math.round(length / 60)
  // the interval is still happening (live): the slider ends at "now", and the rest of the
  // 15 minutes is only a faded scale, with no track, so it does not look reachable. A time
  // label that close to "Now" is left out, so the two never overlap
  const unfinished = limit < length

  // A second of the interval. Keys may go past its start or end: the page then moves to the
  // interval before or after (onSeek gets a negative second, or one past the end). In an
  // interval still happening, nothing goes past "Now"
  function seek(next) {
    const rounded = Math.round(next)
    onSeek(unfinished ? Math.max(Math.min(rounded, limit), rounded < 0 ? rounded : 0) : rounded)
  }

  // arrows 1 s (with Shift 10 s), Page Up / Page Down 1 minute, Home the start, End the
  // furthest reachable second
  function onKeyDown(event) {
    const by = event.shiftKey ? 10 : 1
    const steps = {
      ArrowLeft: -by,
      ArrowDown: -by,
      ArrowRight: by,
      ArrowUp: by,
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
      className={className}
      action={
        <Button size="sm" variant="secondary" onClick={onBack}>
          ← Back to 24 hours
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
          <PlayPauseIcon paused={paused} />
          {paused ? 'Play' : 'Pause'}
        </Button>
        <Button
          size="sm"
          variant="secondary"
          className="interval-slider-step"
          onClick={onPrevious}
          disabled={!onPrevious}
          aria-label="Previous interval"
          title="Previous interval"
        >
          ‹
        </Button>
        <span className="interval-slider-time">{clock(startMs + value * 1000, true)}</span>
        <Button
          size="sm"
          variant="secondary"
          className="interval-slider-step"
          onClick={onNext}
          disabled={!onNext}
          aria-label="Next interval"
          title="Next interval"
        >
          ›
        </Button>
        <span className="interval-slider-range">
          {clock(startMs, false)}–{clock(startMs + length * 1000, false)}
        </span>
      </div>

      <div
        className={`interval-slider-plot ${unfinished ? 'unfinished' : ''}`}
        style={{ '--reachable': `${(limit / length) * 100}%` }}
        onPointerDown={(event) => {
          if (event.button !== 0) return
          const box = event.currentTarget.getBoundingClientRect()
          const width = box.width || 1
          // a press on the bar first puts the knob there, as usual
          const at = Math.max(0, Math.min(limit, ((event.clientX - box.left) / width) * length))
          event.currentTarget.setPointerCapture(event.pointerId)
          event.currentTarget.querySelector('input')?.focus()
          dragRef.current = { x: event.clientX, ms: startRef.current + at * 1000, width }
          onScrubStart?.()
          seek(at)
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current
          if (!drag) return
          const moved = event.clientX - drag.x
          const ms = drag.ms + (moved / drag.width) * length * 1000
          if (onDragTo) onDragTo(ms, moved >= (drag.moved ?? 0) ? 1 : -1)
          else seek((ms - startRef.current) / 1000)
          drag.moved = moved
        }}
        onPointerUp={() => {
          if (!dragRef.current) return
          dragRef.current = null
          onScrubEnd?.()
        }}
        onPointerCancel={() => {
          if (!dragRef.current) return
          dragRef.current = null
          onScrubEnd?.()
        }}
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
            Back to live
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
