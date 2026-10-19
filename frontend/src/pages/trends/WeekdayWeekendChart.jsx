import Card from '../../components/Card'
import { displayUnit, formatKpiValue, hasValue, KPI_DEFINITIONS } from '../../utils/kpi'
import './WeekdayWeekendChart.css'

// The rows, in order, with the label shown for each KPI
const ROWS = [
  { kpi: 'control_delay', label: 'Control delay' },
  { kpi: 'queue_length', label: '95th-pct queue' },
  { kpi: 'throughput', label: 'Throughput' },
  { kpi: 'volume_to_capacity_ratio', label: 'Critical v/c' },
]

// Weekdays vs weekends: for each KPI, one bar for weekdays and one for
// weekends. Each row has its own scale, because the KPIs have different
// units: compare the two bars in a row, not bars in different rows.
//
//   pairs   data.weekdayWeekend: { control_delay: { weekdays, weekends }, … }
function WeekdayWeekendChart({ pairs }) {
  const legend = (
    <div className="ww-legend">
      <span className="ww-legend-item">
        <span className="ww-swatch ww-weekdays" /> Weekdays
      </span>
      <span className="ww-legend-item">
        <span className="ww-swatch ww-weekends" /> Weekends
      </span>
    </div>
  )

  return (
    <Card title="Weekdays vs weekends" className="ww-card">
      {legend}
      <div className="ww-rows">
        {ROWS.filter((row) => pairs[row.kpi]).map((row) => {
          const { weekdays, weekends } = pairs[row.kpi]
          const unit = displayUnit(weekdays?.unit ?? weekends?.unit)
          const max = Math.max(
            hasValue(weekdays) ? weekdays.value : 0,
            hasValue(weekends) ? weekends.value : 0,
          )

          return (
            <div key={row.kpi} className="ww-row">
              <p className="ww-label">
                {row.label ?? KPI_DEFINITIONS[row.kpi]?.label}
                {unit && <span className="ww-unit"> {unit}</span>}
              </p>
              <div className="ww-bars">
                <Bar result={weekdays} max={max} kind="weekdays" name="Weekdays" />
                <Bar result={weekends} max={max} kind="weekends" name="Weekends" />
              </div>
            </div>
          )
        })}
      </div>

      <p className="ww-note">Each row has its own scale: compare the two bars within a row.</p>
    </Card>
  )
}

// One bar with its value at the end. No value: a dashed outline and
// "Unavailable", never a zero-length bar.
function Bar({ result, max, kind, name }) {
  if (!hasValue(result)) {
    return (
      <div className="ww-bar-line" title={result?.reason ?? undefined}>
        <span className="ww-bar ww-bar-missing" />
        <span className="ww-value ww-value-missing">Unavailable</span>
      </div>
    )
  }

  // The longer bar fills 85% of the row, leaving room for its number
  const share = max > 0 ? (result.value / max) * 85 : 0

  return (
    <div className="ww-bar-line">
      <span
        className={`ww-bar ww-${kind}`}
        style={{ width: `${Math.max(share, 1)}%` }}
        role="img"
        aria-label={`${name}: ${formatKpiValue(result)}`}
      />
      <span className="ww-value">{formatKpiValue(result)}</span>
    </div>
  )
}

export default WeekdayWeekendChart