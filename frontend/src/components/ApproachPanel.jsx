import { useState } from 'react'
import InfoTip from './InfoTip'
import LosBadge from './LosBadge'
import { displayUnit, formatKpiValue, hasValue, isOverLimit, OVER_LIMIT } from '../utils/kpi'
import './ApproachPanel.css'

// The approaches of the intersection, in two parts:
//   ApproachChips     one small chip per approach with its LOS and delay, along the bottom of the
//                     3D scene. Clicking a chip (or the approach's lanes) selects it.
//   ApproachDetails   the selected approach, shown in the side column in place of the
//                     intersection's KPIs (not on the scene, so it never covers the junction):
//                     four numbers for the whole approach, then one card per movement with a
//                     direction arrow, its LOS, its delay and queue. Opening a movement's card
//                     shows all its KPIs; the first one is open to begin with.
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
  { kpi: 'volume_to_capacity_ratio', label: 'D / C', title: 'Demand / capacity' },
  { kpi: 'throughput', label: 'Flow' },
]

// a movement's KPIs when its card is open, under its control delay. Queue storage ratio is not
// shown: the backend leaves it out of kpis.json (kpi_engine.md, section 6.5).
const DETAILS = [
  { kpi: 'queue_length', label: 'Queue' },
  { kpi: 'volume_to_capacity_ratio', label: 'Demand / capacity' },
  { kpi: 'throughput', label: 'Flow' },
  { kpi: 'capacity', label: 'Capacity' },
  { kpi: 'saturation_flow_rate', label: 'Saturation flow' },
  { kpi: 'queue_duration', label: 'Queue time' },
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
          <div key={s.kpi} title={s.title}>
            <dt>{s.label}</dt>
            <dd>
              <KpiValue result={approach.kpis[s.kpi]} withUnit />
            </dd>
          </div>
        ))}
      </dl>

      <h3 className="approach-movements-title">
        By movement
        {shared && (
          <InfoTip label="About the shared lane" align="end">
            {shared}
          </InfoTip>
        )}
      </h3>
      <ul className="approach-movements">
        {approach.movements.map((m, i) => (
          <MovementItem key={m.movement_id} movement={m} startOpen={i === 0} />
        ))}
      </ul>
    </section>
  )
}

// One movement as a card: arrow, name and LOS, with its delay and queue. Opening it shows its
// control delay large and its other KPIs under it.
function MovementItem({ movement, startOpen }) {
  const [expanded, setExpanded] = useState(startOpen)
  const { arrow, name } = direction(movement.label)
  const detailsId = `movement-${movement.movement_id}`

  return (
    <li className={`approach-movement${expanded ? ' approach-movement-open' : ''}`}>
      <div className="approach-movement-main">
        <span className="approach-movement-arrow" aria-hidden="true">
          {arrow}
        </span>
        <span className="approach-movement-name">{name}</span>
        <KpiValue result={movement.kpis.level_of_service} />
        <button
          type="button"
          className="approach-movement-toggle"
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-label={`${expanded ? 'Hide' : 'Show'} all KPIs of ${name}`}
          onClick={() => setExpanded((e) => !e)}
        >
          <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
            <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        </button>
      </div>

      {!expanded && (
        <div className="approach-movement-numbers">
          <span>
            Delay <KpiValue result={movement.kpis.control_delay} withUnit />
          </span>
          <span>
            Queue <KpiValue result={movement.kpis.queue_length} withUnit />
          </span>
        </div>
      )}

      {expanded && (
        <div id={detailsId} className="approach-movement-details">
          <div className="approach-movement-delay">
            <span>Control delay</span>
            <strong>
              <KpiValue result={movement.kpis.control_delay} withUnit />
            </strong>
          </div>
          <dl className="approach-movement-grid">
            {DETAILS.map((d) => (
              <div key={d.kpi}>
                <dt>{d.label}</dt>
                <dd>
                  <KpiValue result={movement.kpis[d.kpi]} withUnit />
                </dd>
              </div>
            ))}
          </dl>
        </div>
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

// One sentence for the info button next to "By movement" when movements share a lane and so
// show the same queue,
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
