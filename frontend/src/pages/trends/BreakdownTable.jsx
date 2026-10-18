import { Fragment, useEffect, useState } from 'react'
import Card from '../../components/Card'
import EmptyState from '../../components/EmptyState'
import LosBadge from '../../components/LosBadge'
import Select from '../../components/Select'
import { getBreakdown } from '../../services/trendsService'
import { displayUnit, formatKpiValue, hasValue, isOverLimit, OVER_LIMIT } from '../../utils/kpi'
import './BreakdownTable.css'

// The extra menu choice that shows the hour picker
const SINGLE_HOUR = 'single-hour'

// 00:00–01:00 … 23:00–00:00
const HOURS = Array.from({ length: 24 }, (_, h) => {
  const from = String(h).padStart(2, '0')
  const to = String((h + 1) % 24).padStart(2, '0')
  return { value: from, label: `${from}:00–${to}:00` }
})

// The table's columns, in order. The unit in each heading is read from the
// data, so it always matches what the backend sent.
const COLUMNS = [
  { kpi: 'control_delay', label: 'Control delay' },
  { kpi: 'level_of_service', label: 'LOS' },
  { kpi: 'volume_to_capacity_ratio', label: 'v/c' },
  { kpi: 'queue_length', label: '95th-pct queue' },
  { kpi: 'queue_storage_ratio', label: 'Storage ratio' },
  { kpi: 'queue_duration', label: 'Queue duration' },
  { kpi: 'throughput', label: 'Throughput' },
]

// Approach and movement breakdown: every KPI for each approach, its
// movements (click an approach to fold them away) and the intersection,
// for one time window. It loads its own data, so changing the window does
// not reload the rest of the page.
//
//   filters   { periodDays, dayType, approachId } from the page
//   windows   the time windows to choose from: [{ id, label, default }]
//
// Besides the listed windows, the user can pick any single hour. That is
// sent to the service as 'hour-HH', e.g. 'hour-17' for 17:00–18:00.
function BreakdownTable({ filters, windows }) {
  const [choice, setChoice] = useState(
    (windows.find((w) => w.default) ?? windows[0])?.id,
  )
  const [hour, setHour] = useState('17')
  const windowId = choice === SINGLE_HOUR ? `hour-${hour}` : choice
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [closed, setClosed] = useState(new Set()) // approaches folded away

  const { periodDays, dayType, approachId } = filters

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    getBreakdown({ periodDays, dayType, approachId, windowId })
      .then((result) => {
        if (cancelled) return
        setData(result)
        setError(null)
      })
      .catch((err) => {
        if (!cancelled) setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [periodDays, dayType, approachId, windowId])

  function toggle(id) {
    const next = new Set(closed)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setClosed(next)
  }

  const menu = (
    <div className="bd-menu">
      <Select
        label="Window"
        size="sm"
        options={[
          ...windows.map((w) => ({ value: w.id, label: w.label })),
          { value: SINGLE_HOUR, label: 'Single hour…' },
        ]}
        value={choice}
        onChange={setChoice}
      />
      {/* The hour picker appears only for "Single hour" */}
      {choice === SINGLE_HOUR && (
        <Select
          ariaLabel="Hour"
          size="sm"
          options={HOURS}
          value={hour}
          onChange={setHour}
        />
      )}
    </div>
  )

  if (error) {
    return (
      <Card title="Approach and movement breakdown" action={menu}>
        <EmptyState variant="error" title="Breakdown unavailable">
          {error.message}
        </EmptyState>
      </Card>
    )
  }

  if (!data) {
    return (
      <Card title="Approach and movement breakdown" action={menu}>
        <EmptyState>Loading breakdown…</EmptyState>
      </Card>
    )
  }

  const units = unitsFrom(data)

  return (
    <Card title="Approach and movement breakdown" action={menu}>
      {/* The table scrolls sideways on a narrow screen instead of squashing */}
      <div className={`bd-scroll ${loading ? 'is-loading' : ''}`} aria-busy={loading}>
        <table className="bd-table">
          <caption className="bd-caption">
            KPIs by approach and movement, {data.window.label}
          </caption>
          <thead>
            <tr>
              <th scope="col" className="bd-name-col">Approach / movement</th>
              {COLUMNS.map((c) => (
                <th key={c.kpi} scope="col">
                  {c.label}
                  {units[c.kpi] && <span className="bd-unit"> ({units[c.kpi]})</span>}
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            {data.approaches.map((approach) => {
              const isOpen = !closed.has(approach.approach_id)

              return (
                <Fragment key={approach.approach_id}>
                  <tr className="bd-approach">
                    <th scope="row" className="bd-name-col">
                      <button
                        type="button"
                        className="bd-toggle"
                        aria-expanded={isOpen}
                        onClick={() => toggle(approach.approach_id)}
                      >
                        <span className="bd-chevron" aria-hidden="true" />
                        {approach.label}
                      </button>
                    </th>
                    <Cells results={approach.results} />
                  </tr>

                  {isOpen &&
                    approach.movements.map((movement) => (
                      <tr key={movement.movement_id} className="bd-movement">
                        <th scope="row" className="bd-name-col">
                          {movement.label}
                        </th>
                        <Cells results={movement.results} />
                      </tr>
                    ))}
                </Fragment>
              )
            })}
          </tbody>

          <tfoot>
            <tr className="bd-total">
              <th scope="row" className="bd-name-col">Intersection</th>
              <Cells results={data.intersection.results} criticalVc />
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="bd-footnote">
        Approach delay = flow-weighted average of its movements; approach v/c, queue and
        storage ratio = worst movement; throughput = sum. Intersection v/c is the critical
        v/c (Xc). A movement with v/c above 1.0 is LOS F regardless of delay. Highlighted:
        v/c above 1.0 and storage ratio of 1.0 or more. "Shared lane" = measured on a lane used by two movements.
      </p>
    </Card>
  )
}

// One row's cells, one per column
function Cells({ results, criticalVc = false }) {
  return COLUMNS.map((c) => {
    const result = results[c.kpi]

    if (c.kpi === 'level_of_service') {
      return (
        <td key={c.kpi}>
          <LosBadge grade={hasValue(result) ? result.los_grade : undefined} />
        </td>
      )
    }

    if (!hasValue(result)) {
      return (
        <td key={c.kpi} className="bd-missing" title={result?.reason ?? undefined}>
          {formatKpiValue(result)}
        </td>
      )
    }

    const over = isOverLimit(result)

    return (
      <td key={c.kpi} className={over ? 'bd-over' : ''}>
        {formatKpiValue(result)}
        {/* Said in words for screen readers, not only by the color */}
        {over && <span className="bd-hidden"> ({OVER_LIMIT[c.kpi].label})</span>}
        {criticalVc && c.kpi === 'volume_to_capacity_ratio' && (
          <span className="bd-suffix" title="Critical v/c of the intersection">
            {' '}
            Xc
          </span>
        )}
        {result.is_shared_value && (
          <span
            className="bd-shared"
            title={`Measured on shared lane ${result.measured_on_lane_id ?? ''}`.trim()}
          >
            Shared lane
          </span>
        )}
      </td>
    )
  })
}

// The unit of each column, from the first result that has one
function unitsFrom(data) {
  const all = [data.intersection, ...data.approaches, ...data.approaches.flatMap((a) => a.movements)]
  const units = {}
  for (const c of COLUMNS) {
    const unit = all.map((e) => e.results[c.kpi]?.unit).find(Boolean)
    units[c.kpi] = displayUnit(unit)
  }
  return units
}

export default BreakdownTable