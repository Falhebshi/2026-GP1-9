import { useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { METHOD_LABELS } from '../utils/kpi'
import './MethodTag.css'

// What a method tag means, shown on hover or keyboard focus. Only HCM
// values are tagged: simulated values are the default.
const METHOD_HINTS = {
  hcm: 'Calculated with the Highway Capacity Manual method from the traffic demand, lanes and signal timing, not measured in the simulation.',
}

// A small tag after a KPI saying how its value was obtained ("HCM"), with
// its meaning on hover or focus. The meaning floats above the page, so a
// table that scrolls sideways cannot cut it off.
//   method   the KpiResult's method; only 'hcm' shows a tag
function MethodTag({ method, className = '' }) {
  const id = useId()
  const ref = useRef(null)
  const [place, setPlace] = useState(null)

  if (!METHOD_HINTS[method]) return null

  function show() {
    const box = ref.current.getBoundingClientRect()
    const left = Math.min(Math.max(box.left, 8), window.innerWidth - 288)
    setPlace({ top: box.bottom + 6, left })
  }

  return (
    <>
      <span
        ref={ref}
        className={`method-tag ${className}`}
        tabIndex={0}
        aria-describedby={id}
        onPointerEnter={show}
        onPointerLeave={() => setPlace(null)}
        onFocus={show}
        onBlur={() => setPlace(null)}
      >
        {METHOD_LABELS[method]}
      </span>
      {createPortal(
        <span
          role="tooltip"
          id={id}
          className={`method-tag-hint ${place ? 'method-tag-hint-open' : ''}`}
          style={place ?? undefined}
        >
          {METHOD_HINTS[method]}
        </span>,
        document.body,
      )}
    </>
  )
}

export default MethodTag
