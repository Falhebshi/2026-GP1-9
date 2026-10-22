import { Fragment, useState } from 'react'
import LosBadge from './LosBadge'
import { displayUnit, formatKpiValue, hasValue, isOverLimit, OVER_LIMIT } from '../utils/kpi'
import './ApproachPanel.css'

// The approaches of the intersection along the bottom of the 3D scene, one small chip each with
// its LOS and delay. Clicking a chip (or the approach's lanes on the map) opens a card above it
// with the approach's KPIs and its movements, so you can see which movement causes the trouble.
// Clicking a movement shows its other KPIs (capacity, saturation flow, queue time, storage
// ratio) under it. Clicking the chip again, or the ×, closes the card.
//
//   approaches   list of { approach_id, arm, road, kpis, movements: [{ movement_id, label, kpis }] }
//                where kpis maps a KPI name to its KpiResult, e.g. kpis.control_delay
//   openId       approach_id of the open approach, or null
//   onToggle     called with an approach_id when its chip is clicked
// Values are formatted with src/utils/kpi.js, so a missing value shows "Unavailable" or
// "Not applicable" (with the reason on hover), never 0.

const COLUMNS = [
  { kpi: 'control_delay', label: 'Delay' },
  { kpi: 'level_of_service', label: 'LOS' },
  { kpi: 'volume_to_capacity_ratio', label: 'v/c' },
  { kpi: 'queue_length', label: 'Queue' },
  { kpi: 'throughput', label: 'Flow' },
]

// the KPIs shown under a movement when it is clicked
const DETAILS = [
  { kpi: 'capacity', label: 'Capacity' },
  { kpi: 'saturation_flow_rate', label: 'Sat. flow' },
  { kpi: 'queue_duration', label: 'Queue time' },
  { kpi: 'queue_storage_ratio', label: 'Storage ratio' },
]

function ApproachPanel({ approaches, openId, onToggle }) {
  if (!approaches?.length) return null
  const open = approaches.find((a) => a.approach_id === openId)
  const shared = open ? sharedLaneNote(open.movements) : null

  return (
    <div className="approach-panel">
      {open && (
        <div className="approach-card" role="region" aria-label={`${open.arm} approach`}>
          <div className="approach-card-head">
            <div>
              <span className="approach-card-title">{open.arm} approach</span>
              <span className="approach-card-road">{open.road}</span>
            </div>
            <button
              type="button"
              className="approach-close"
              onClick={() => onToggle(open.approach_id)}
              aria-label="Close"
            >
              ×
            </button>
          </div>

          <table className="approach-table">
            <thead>
              <tr>
                <th />
                {COLUMNS.map((c) => {
                  const unit = displayUnit(open.kpis[c.kpi]?.unit)
                  return (
                    <th key={c.kpi}>
                      {c.label}
                      {unit && <small> {unit}</small>}
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              <tr className="approach-total">
                <th scope="row">Whole approach</th>
                {COLUMNS.map((c) => (
                  <td key={c.kpi}>
                    <KpiValue result={open.kpis[c.kpi]} />
                  </td>
                ))}
              </tr>
              {open.movements.map((m) => (
                <MovementRows key={m.movement_id} movement={m} />
              ))}
            </tbody>
          </table>

          {shared && <p className="approach-note">{shared}</p>}
        </div>
      )}

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
    </div>
  )
}

// A movement's row, and its other KPIs under it once it is clicked
function MovementRows({ movement }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <Fragment>
      <tr
        className={`approach-movement-row ${expanded ? 'approach-movement-open' : ''}`}
        onClick={() => setExpanded((e) => !e)}
      >
        <th scope="row">
          <button type="button" className="approach-movement-toggle" aria-expanded={expanded}>
            <span className="approach-arrow" aria-hidden="true">
              ›
            </span>
            {movement.label}
          </button>
        </th>
        {COLUMNS.map((c) => (
          <td key={c.kpi}>
            <KpiValue result={movement.kpis[c.kpi]} />
          </td>
        ))}
      </tr>
      {expanded && (
        <tr className="approach-movement-details">
          <td colSpan={COLUMNS.length + 1}>
            <dl>
              {DETAILS.map((d) => (
                <div key={d.kpi}>
                  <dt>{d.label}</dt>
                  <dd>
                    <KpiValue result={movement.kpis[d.kpi]} withUnit />
                  </dd>
                </div>
              ))}
            </dl>
          </td>
        </tr>
      )}
    </Fragment>
  )
}

// One sentence under the table when movements share a lane and so show the same queue,
// e.g. "Through and Left share a lane, so they show the same queue."
function sharedLaneNote(movements) {
  const names = movements
    .filter((m) => m.kpis.queue_length?.is_shared_value)
    .map((m) => m.label)
  if (names.length < 2) return null
  return `${names.slice(0, -1).join(', ')} and ${names.at(-1)} share a lane, so they show the same queue.`
}

// One KPI result in the table or a chip
//   withUnit   adds the unit after the number (the table columns show it in the header)
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
