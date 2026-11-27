// The Play / Pause icon of the playback buttons (Current Traffic's timeline and IntervalSlider):
// two slim bars, or a triangle, in the button's text colour and as tall as its text
function PlayPauseIcon({ paused }) {
  return (
    <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true" focusable="false">
      {paused ? (
        <path d="M1 0.5 L9.5 6 L1 11.5 Z" fill="currentColor" />
      ) : (
        <>
          <rect x="1.5" y="0.5" width="2.2" height="11" rx="0.6" fill="currentColor" />
          <rect x="6.3" y="0.5" width="2.2" height="11" rx="0.6" fill="currentColor" />
        </>
      )}
    </svg>
  )
}

export default PlayPauseIcon
