import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import './InfoTip.css'

// A small "i" button next to a heading or value, with a short explanation that is shown only
// when asked for, instead of a box that always takes space.
//
//   label     what the button is for, read by screen readers, e.g. "About the sample run"
//   open      "hover"  the text shows while the pointer is on the button or the text, and while
//                      the button has keyboard focus
//             "click"  the text shows when the button is clicked, and hides on a second click,
//                      a click outside or Escape
//   align     "start"  the text box lines up with the button's left edge
//             "end"    with its right edge, for buttons near the right of the screen
//
// The text between <InfoTip> and </InfoTip> is the explanation. Warnings and errors the user
// must see at once stay in a Notice; this is for explanations a user may want to read.
function InfoTip({ label = 'More information', open: mode = 'hover', align = 'start', children }) {
  const [shown, setShown] = useState(false)
  const [shift, setShift] = useState(0) // px the box moves sideways to stay inside the window
  const rootRef = useRef(null)
  const boxRef = useRef(null)
  const hideTimer = useRef(null)
  const id = useId()

  // Escape closes it; for "click", so does a click anywhere outside
  useEffect(() => {
    if (!shown) return undefined
    const onKey = (event) => {
      if (event.key === 'Escape') setShown(false)
    }
    const onClick = (event) => {
      if (!rootRef.current?.contains(event.target)) setShown(false)
    }
    document.addEventListener('keydown', onKey)
    if (mode === 'click') document.addEventListener('mousedown', onClick)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('mousedown', onClick)
    }
  }, [shown, mode])

  useEffect(() => () => clearTimeout(hideTimer.current), [])

  // Near the edge of the window the box would be cut off: move it back inside, with a small margin
  useLayoutEffect(() => {
    if (!shown || !boxRef.current) {
      setShift(0)
      return
    }
    const { left, right } = boxRef.current.getBoundingClientRect()
    const edge = document.documentElement.clientWidth - EDGE_PX
    if (right > edge) setShift(edge - right)
    else if (left < EDGE_PX) setShift(EDGE_PX - left)
  }, [shown])

  // Hover: a short delay before hiding, so the pointer can move from the button to the text
  const show = () => {
    clearTimeout(hideTimer.current)
    setShown(true)
  }
  const hideSoon = () => {
    clearTimeout(hideTimer.current)
    hideTimer.current = setTimeout(() => setShown(false), 150)
  }
  const hover =
    mode === 'hover'
      ? { onMouseEnter: show, onMouseLeave: hideSoon, onFocus: show, onBlur: hideSoon }
      : {}

  return (
    <span className="info-tip" ref={rootRef} {...hover}>
      <button
        type="button"
        className={`info-tip-button${shown ? ' info-tip-button-open' : ''}`}
        aria-label={label}
        aria-expanded={mode === 'click' ? shown : undefined}
        aria-describedby={mode === 'hover' && shown ? id : undefined}
        aria-controls={mode === 'click' ? id : undefined}
        onClick={mode === 'click' ? () => setShown((value) => !value) : undefined}
      >
        <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
          <circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" strokeWidth="1.4" />
          <path d="M8 7v4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="8" cy="4.8" r="0.95" fill="currentColor" />
        </svg>
      </button>
      {shown && (
        <span
          ref={boxRef}
          id={id}
          style={shift ? { transform: `translateX(${shift}px)` } : undefined}
          role={mode === 'hover' ? 'tooltip' : 'dialog'}
          aria-label={mode === 'click' ? label : undefined}
          className={`info-tip-box info-tip-${align}`}
        >
          {children}
        </span>
      )}
    </span>
  )
}

// How close the box may come to the edge of the window
const EDGE_PX = 8

export default InfoTip
