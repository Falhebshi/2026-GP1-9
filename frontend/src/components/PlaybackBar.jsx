import Button from './Button'
import SegmentedControl from './SegmentedControl'
import './PlaybackBar.css'

// Play / pause, a slider showing where the playback is, and optionally a
// speed control. Used under a simulation on Traffic Forecast and on
// Recommendation Details.
//
// The bar does not keep time itself: it shows the values it is given and
// reports what the user does. The clock lives in the usePlayback hook
// (src/hooks/usePlayback.js), which a page connects like this:
//
//   const playback = usePlayback({ duration: 3600 })
//
//   <PlaybackBar
//     duration={3600}
//     time={playback.time}        onTimeChange={playback.setTime}
//     playing={playback.playing}  onPlayingChange={playback.setPlaying}
//     speed={playback.speed}      onSpeedChange={playback.setSpeed}
//   />
//
//   duration           length of the whole slider, in simulated seconds
//   time               where the playback is, in simulated seconds
//   onTimeChange       called with the new time when the user drags the knob
//   playing            true while playing
//   onPlayingChange    called with true or false when Play / Pause is clicked
//   speed              the current speed. Leave speed out to hide the control.
//   onSpeedChange      called with the new speed
//   speedOptions       the speed choices (x5, x10, x20 unless you say otherwise)
//   marks              labelled points on the slider, as a list:
//                      [{ time: 900, label: '15 min' }]
//   selectedMark       the time of the selected mark, which is highlighted
//   onMarkSelect       called with a mark's time when the user clicks it.
//                      The page decides what that does, e.g. play from there.
//   disabled           true switches every control off, e.g. when the
//                      simulation did not run
function PlaybackBar({
  duration,
  time,
  onTimeChange,
  playing,
  onPlayingChange,
  speed,
  onSpeedChange,
  speedOptions = DEFAULT_SPEEDS,
  marks = [],
  selectedMark,
  onMarkSelect,
  disabled = false,
  className = '',
}) {
  // A time as a share of the slider, from 0 (start) to 1 (end)
  function fraction(seconds) {
    if (!duration) return 0
    return Math.min(Math.max(seconds / duration, 0), 1)
  }

  const readout = `${formatClock(time)} / ${formatClock(duration)}`

  return (
    // A <fieldset> switches off everything inside it when it is disabled
    <fieldset
      className={`playback-bar ${marks.length > 0 ? 'has-marks' : ''} ${className}`}
      disabled={disabled}
      aria-label="Playback controls"
    >
      <Button
        variant="secondary"
        className="playback-toggle"
        onClick={() => onPlayingChange(!playing)}
      >
        {playing ? <PauseIcon /> : <PlayIcon />}
        {playing ? 'Pause' : 'Play'}
      </Button>

      {/* --progress tells the CSS how much of the line to fill */}
      <div className="playback-track" style={{ '--progress': fraction(time) }}>
        <div className="playback-rail" />

        {/* The marks: a dot on the line, and a label above it to click */}
        {marks.map((mark) => {
          const isSelected = mark.time === selectedMark
          const isPassed = mark.time <= time // the knob has reached it

          return (
            <div
              key={mark.time}
              className="playback-mark"
              style={{ '--at': fraction(mark.time) }}
            >
              <button
                type="button"
                className={`playback-mark-label ${isSelected ? 'active' : ''}`}
                aria-pressed={isSelected}
                onClick={() => onMarkSelect?.(mark.time)}
              >
                {mark.label}
              </button>
              <span className={`playback-mark-dot ${isPassed ? 'passed' : ''}`} />
            </div>
          )
        })}

        <input
          type="range"
          className="playback-slider"
          min={0}
          max={duration}
          step={1}
          value={Math.round(time)}
          aria-label="Playback position"
          aria-valuetext={readout}
          onChange={(event) => onTimeChange(Number(event.target.value))}
        />
      </div>

      <span className="playback-time">{readout}</span>

      {speed !== undefined && (
        <SegmentedControl
          label="Acceleration rate"
          size="sm"
          options={speedOptions}
          value={speed}
          onChange={onSpeedChange}
        />
      )}
    </fieldset>
  )
}

// ---- Helpers ---------------------------------------------------------------

const DEFAULT_SPEEDS = [
  { value: 5, label: 'x5' },
  { value: 10, label: 'x10' },
  { value: 20, label: 'x20' },
]

// 754 seconds becomes "12:34" (minutes:seconds)
function formatClock(seconds) {
  const minutes = Math.floor(seconds / 60)
  const rest = Math.floor(seconds % 60)
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
}

function PlayIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2.5 1.2v9.6L10.5 6z" fill="currentColor" />
    </svg>
  )
}

function PauseIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2.5 1.5h2.5v9H2.5zM7 1.5h2.5v9H7z" fill="currentColor" />
    </svg>
  )
}

export default PlaybackBar