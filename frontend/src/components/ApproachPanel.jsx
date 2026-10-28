import { useState } from 'react'
import LosBadge from './LosBadge'
import { displayUnit, formatKpiValue, hasValue, isOverLimit, OVER_LIMIT } from '../utils/kpi'
import './ApproachPanel.css'

// The approaches of the intersection, in two parts:
//   ApproachChips     one small chip per approach with its LOS and delay, along the bottom of the
//                     3D scene. Clicking a chip (or the approach's lanes) selects it.
//   ApproachDetails   the selected approach, shown next to the scene (not on it, so it never
//                     covers the junction): a one-line summary of the whole approach, then one
//                     row per movement with a direction arrow and three numbers. "More" shows
//                     the movement's other KPIs.
//
//   approaches   list of { approach_id, arm, road, kpis, movements: [{ movement_id, label, kpis }] }
//                where kpis maps a KPI name to its KpiResult, e.g. kpis.control_delay
//   openId       approach_id of the selected approach, or null
//   onToggle     called with an approach_id when its chip (or the close button) is clicked
// Values are formatted with src/utils/kpi.js, so a missing value shows "Unavailable" or
// "Not applicable" (with the reason on hover), never 0.

// the whole approach, in one line
const SUMMARY = [
  { kpi: 'control_delay', label: 'Delay' },
  { kpi: 'queue_length', label: 'Queue' },
  { kpi: 'volume_to_capacity_ratio', label: 'Demand / capacity' },
  { kpi: 'throughput', label: 'Flow' },
]

// the other KPIs of a movement, under "More"
const DETAILS = [
  { kpi: 'volume_to_capacity_ratio', label: 'Demand / capacity' },
  { kpi: 'throughput', label: 'Flow' },
  { kpi: 'capacity', label: 'Capacity' },
  { kpi: 'saturation_flow_rate', label: 'Saturation flow' },
  { kpi: 'queue_duration', label: 'Queue time' },
  { kpi: 'queue_storage_ratio', label: 'Storage used' },
]

// How a movement is named and drawn: its label in the data ('Left', 'Through',
// 'Right (slip lane)') becomes a direction arrow and a plain name
function direction(label) {
  if (label.startsWith('Left')) return { arrow: '↰', name: 'Left turn' }
  if (label.startsWith('Right'))
    return { arrow: '↱', name: label.includes('slip') ? 'Right turn (slip lane)' : 'Right turn' }
  if (label.startsWith('U')) return { arrow: '↶', name: 'U-turn' }
  return { arrow: '↑', name: 'Straight on' }
}

export function ApproachChips({ approaches, openId, onToggle }) {
  if (!approaches?.length) return null

  return (
    <div className="approach-chips" role="group" aria-label="Approaches">
      <span className="approach-chips-label">Approaches</span>
      {approaches.map((a) => (
        <button
          key={a.approach_id}
          type="button"
          className={`approach-chip ${a.approach_id === openId ? 'approach-chip-active' : ''}`}
          aria-pressed={a.approach_id === openId}
          onClick={() => onToggle(a.approach_id)}
        >
          <span className="approach-chip-name">{a.arm}</span>
          <KpiValue result={a.kpis.level_of_service} />
          <span className="approach-chip-delay">
            <KpiValue result={a.kpis.control_delay} withUnit />
          </span>
        </button>
      ))}
    </div>
  )
}

export function ApproachDetails({ approach, onClose }) {
  if (!approach) return null
  const shared = sharedLaneNote(approach.movements)

  return (
    <section className="approach-details" aria-label={`${approach.arm} approach`}>
      <header className="approach-details-head">
        <div>
          <h2 className="approach-details-title">
            {approach.arm} approach <KpiValue result={approach.kpis.level_of_service} />
          </h2>
          <span className="approach-details-road">{approach.road}</span>
        </div>
        <button type="button" className="approach-close" onClick={onClose} aria-label="Close">
          ×
        </button>
      </header>

      <dl className="approach-summary">
        {SUMMARY.map((s) => (
          <div key={s.kpi}>
            <dt>{s.label}</dt>
            <dd>
              <KpiValue result={approach.kpis[s.kpi]} withUnit />
            </dd>
          </div>
        ))}
      </dl>

      <h3 className="approach-movements-title">By movement</h3>
      <ul className="approach-movements">
        {approach.movements.map((m) => (
          <MovementItem key={m.movement_id} movement={m} />
        ))}
      </ul>

      {shared && <p className="approach-note">{shared}</p>}
    </section>
  )
}

// One movement: arrow, name, LOS, delay and queue; "More" shows the rest
function MovementItem({ movement }) {
  const [expanded, setExpanded] = useState(false)
  const { arrow, name } = direction(movement.label)

  return (
    <li className="approach-movement">
      <div className="approach-movement-main">
        <span className="approach-movement-arrow" aria-hidden="true">
          {arrow}
        </span>
        <span className="approach-movement-name">{name}</span>
        <KpiValue result={movement.kpis.level_of_service} />
      </div>
      <div className="approach-movement-numbers">
        <span>
          Delay <KpiValue result={movement.kpis.control_delay} withUnit />
        </span>
        <span>
          Queue <KpiValue result={movement.kpis.queue_length} withUnit />
        </span>
        <button
          type="button"
          className="approach-movement-more"
          aria-expanded={expanded}
          onClick={() => setExpanded((e) => !e)}
        >
          {expanded ? 'Less' : 'More'}
        </button>
      </div>
      {expanded && (
        <dl className="approach-movement-details">
          {DETAILS.map((d) => (
            <div key={d.kpi}>
              <dt>{d.label}</dt>
              <dd>
                <KpiValue result={movement.kpis[d.kpi]} withUnit />
              </dd>
            </div>
          ))}
        </dl>
      )}
    </li>
  )
}

// Both parts together, for the component preview page
function ApproachPanel({ approaches, openId, onToggle }) {
  const open = approaches?.find((a) => a.approach_id === openId)

  return (
    <div className="approach-panel">
      <ApproachDetails approach={open} onClose={() => onToggle(openId)} />
      <ApproachChips approaches={approaches} openId={openId} onToggle={onToggle} />
    </div>
  )
}

// One sentence under the movements when they share a lane and so show the same queue,
// e.g. "Straight on and Left turn share a lane, so they show the same queue."
function sharedLaneNote(movements) {
  const names = movements
    .filter((m) => m.kpis.queue_length?.is_shared_value)
    .map((m) => direction(m.label).name)
  if (names.length < 2) return null
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)} share a lane, so they show the same queue.`
}

// One KPI result
//   withUnit   adds the unit after the number
function KpiValue({ result, withUnit = false }) {
  if (!hasValue(result)) {
    return (
      <span className="approach-kpi-missing" title={result?.reason ?? undefined}>
        {formatKpiValue(result)}
      </span>
    )
  }
  if (result.kpi === 'level_of_service') {
    return <LosBadge grade={result.los_grade} className="approach-los" />
  }

  const unit = displayUnit(result.unit)
  const text = withUnit && unit ? `${formatKpiValue(result)} ${unit}` : formatKpiValue(result)

  if (isOverLimit(result)) {
    return (
      <span className="approach-kpi-over" title={OVER_LIMIT[result.kpi].label}>
        {text}
      </span>
    )
  }
  return text
}

export default ApproachPanel
