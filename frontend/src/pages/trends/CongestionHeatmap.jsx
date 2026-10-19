import { useState } from 'react'
import Card from '../../components/Card'
import EmptyState from '../../components/EmptyState'
import { GRADES } from '../../components/LosBadge'
import { displayUnit, formatKpiValue, hasValue } from '../../utils/kpi'
import './CongestionHeatmap.css'

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const HOURS = Array.from({ length: 24 }, (_, h) => h)

// Congestion by hour and day: one square per weekday × hour, colored by the
// level of service of its average control delay, light (A) to dark (F).
// Hover a square to read its grade and delay.
//
//   cells   data.heatmap: [{ day: 0–6, hour: 0–23, result, delay }]
//           result = the level of service (KpiResult), delay = the control
//           delay behind it (KpiResult, optional)
function CongestionHeatmap({ cells }) {
  const [hovered, setHovered] = useState(null) // the cell under the mouse

  const byKey = new Map(cells.map((c) => [`${c.day}-${c.hour}`, c]))

  const legend = (
    <div className="heat-legend" aria-label="Level of service, A to F">
      <span className="heat-legend-text">Average control delay as LOS, per hour</span>
      {GRADES.map((grade) => (
        <span key={grade} className="heat-legend-item">
          <span className={`heat-swatch heat-los-${grade.toLowerCase()}`} />
          {grade}
        </span>
      ))}
    </div>
  )

  if (!cells.some((c) => hasValue(c.result))) {
    return (
      <Card title="Congestion by hour and day" action={legend}>
        <EmptyState>No performance data available for this period.</EmptyState>
      </Card>
    )
  }

  return (
    <Card title="Congestion by hour and day" action={legend}>
      <div className="heat" onPointerLeave={() => setHovered(null)}>
        {/* Hour labels across the top: every 3 hours */}
        <span />
        {HOURS.map((hour) => (
          <span key={hour} className="heat-hour">
            {hour % 3 === 0 ? String(hour).padStart(2, '0') : ''}
          </span>
        ))}

        {DAYS.map((dayName, day) => (
          <Row
            key={dayName}
            day={day}
            dayName={dayName}
            byKey={byKey}
            hovered={hovered}
            onHover={setHovered}
          />
        ))}
      </div>

      <p className="heat-readout" aria-live="polite">
        {hovered ? describe(hovered) : 'Hover a square to see its level of service and delay.'}
      </p>
    </Card>
  )
}

// One weekday: its name, then 24 squares
function Row({ day, dayName, byKey, hovered, onHover }) {
  return (
    <>
      <span className="heat-day">{dayName}</span>
      {HOURS.map((hour) => {
        const cell = byKey.get(`${day}-${hour}`)
        const grade = cell && hasValue(cell.result) ? cell.result.los_grade : null
        const isHovered = hovered && hovered.day === day && hovered.hour === hour

        return (
          <span
            key={hour}
            role="img"
            aria-label={cell ? describe(cell) : `${dayName} ${hourRange(hour)}: no data`}
            className={[
              'heat-cell',
              grade ? `heat-los-${grade.toLowerCase()}` : 'heat-missing',
              isHovered ? 'is-hovered' : '',
            ].join(' ')}
            onPointerEnter={() => cell && onHover(cell)}
          />
        )
      })}
    </>
  )
}

// "Mon 17:00–18:00 · LOS E · 62 s/veh"
function describe(cell) {
  const when = `${DAYS[cell.day]} ${hourRange(cell.hour)}`
  if (!hasValue(cell.result)) return `${when} · ${cell.result.reason ?? 'No data'}`
  const parts = [when, `LOS ${cell.result.los_grade}`]
  if (cell.delay && hasValue(cell.delay)) {
    parts.push(`${formatKpiValue(cell.delay)} ${displayUnit(cell.delay.unit)}`)
  }
  return parts.join(' · ')
}

function hourRange(hour) {
  const start = String(hour).padStart(2, '0')
  const end = String((hour + 1) % 24).padStart(2, '0')
  return `${start}:00–${end}:00`
}

export default CongestionHeatmap