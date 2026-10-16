import { useState } from 'react'
import LocationInfoCard from './LocationInfoCard'
import './LocationSummary.css'

// A small title on top of the map with the intersection's name. Click it (or hover it) to open
// the full Location & General Information card, so the card doesn't cover the map all the time.
//   intersection   same object as LocationInfoCard: { name, area, approaches, signalType }
function LocationSummary({ intersection }) {
  const [pinned, setPinned] = useState(false) // opened by a click, stays open
  const [hover, setHover] = useState(false)
  const open = pinned || hover

  return (
    <div
      className="location-summary"
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <button
        type="button"
        className={`location-summary-title ${open ? 'open' : ''}`}
        aria-expanded={open}
        onClick={() => setPinned((p) => !p)}
      >
        <span className="location-summary-pin" aria-hidden="true" />
        {intersection?.name ?? 'Intersection'}
        <span className="location-summary-chevron" aria-hidden="true" />
      </button>
      {open && <LocationInfoCard intersection={intersection} floating />}
    </div>
  )
}

export default LocationSummary
