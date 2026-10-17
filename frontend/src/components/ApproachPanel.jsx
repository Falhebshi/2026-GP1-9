import { Fragment } from 'react'
import './ApproachPanel.css'

// The approaches of the intersection along the bottom of the 3D scene, one small chip each with
// its LOS and delay. Clicking a chip (or the approach's lanes on the map) opens a card above it
// with the approach's KPIs and its movements, so you can see which movement causes the trouble.
// Clicking the chip again, or the ×, closes it.
//
//   approaches   list of { id, arm, road, kpis, movements: [{ id, type, kpis }] }
//   openId       id of the open approach, or null
//   onToggle     called with an approach id when its chip is clicked
// In a KPI value, null means unavailable and 'na' means the KPI doesn't apply (e.g. LOS for a
// right turn on a slip lane).

const COLUMNS = [
  { key: 'delay', label: 'Delay', unit: 's' },
  { key: 'los', label: 'LOS' },
  { key: 'vc', label: 'v/c' },
  { key: 'queue', label: 'Queue', unit: 'm' },
  { key: 'throughput', label: 'Flow', unit: 'veh/h' },
]

// the KPIs that only fit in the line under each movement
const DETAILS = [
  { key: 'capacity', label: 'Capacity', unit: 'veh/h' },
  { key: 'satFlow', label: 'Sat. flow', unit: 'veh/h' },
  { key: 'queueDuration', label: 'Queue time', unit: 's' },
  { key: 'storage', label: 'Storage ratio' },
]

function ApproachPanel({ approaches, openId, onToggle }) {
  if (!approaches?.length) return null
  const open = approaches.find((a) => a.id === openId)

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
              onClick={() => onToggle(open.id)}
              aria-label="Close"
            >
              ×
            </button>
          </div>

          <table className="approach-table">
            <thead>
              <tr>
                <th />
                {COLUMNS.map((c) => (
                  <th key={c.key}>
                    {c.label}
                    {c.unit && <small> {c.unit}</small>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr className="approach-total">
                <th scope="row">Whole approach</th>
                {COLUMNS.map((c) => (
                  <td key={c.key}>{show(open.kpis[c.key], c.key)}</td>
                ))}
              </tr>
              {open.movements.map((m) => (
                <Fragment key={m.id}>
                  <tr className="approach-movement-row">
                    <th scope="row">{m.type}</th>
                    {COLUMNS.map((c) => (
                      <td key={c.key}>{show(m.kpis[c.key], c.key)}</td>
                    ))}
                  </tr>
                  <tr className="approach-movement-details">
                    <td colSpan={COLUMNS.length + 1}>
                      {DETAILS.map((d) => (
                        <span key={d.key}>
                          {d.label} <b>{show(m.kpis[d.key], d.key)}</b>
                          {typeof m.kpis[d.key] === 'number' && d.unit ? ` ${d.unit}` : ''}
                        </span>
                      ))}
                    </td>
                  </tr>
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="approach-chips" role="group" aria-label="Approaches">
        <span className="approach-chips-label">Approaches</span>
        {approaches.map((a) => (
          <button
            key={a.id}
            type="button"
            className={`approach-chip ${a.id === openId ? 'approach-chip-active' : ''}`}
            aria-pressed={a.id === openId}
            onClick={() => onToggle(a.id)}
          >
            <span className="approach-chip-name">{a.arm}</span>
            {show(a.kpis.los, 'los')}
            <span className="approach-chip-delay">{show(a.kpis.delay, 'delay')} s</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function show(value, key) {
  if (value === 'na') return <span className="approach-kpi-missing">N/A</span>
  if (value === null || value === undefined) return <span className="approach-kpi-missing">Unavailable</span>
  if (key === 'los') return <span className={`approach-los approach-los-${value}`}>{value}</span>
  if (key === 'vc' || key === 'storage') {
    const text = value.toFixed(2)
    return value >= 1 ? <span className="approach-kpi-over">{text}</span> : text
  }
  return value.toLocaleString('en-US')
}

export default ApproachPanel
