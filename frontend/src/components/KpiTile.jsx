import './KpiTile.css'

// One KPI: a label, a value with its unit, and how much it changed.
//
//   label        name of the KPI, e.g. "Control Delay"
//   value        a number or text. Leave it out (or pass null) when the KPI
//                has no valid result: the tile then shows "Unavailable"
//                instead of a misleading 0.
//   unit         e.g. "s", "m", "km/h" (optional, for unitless KPIs)
//   change       how much the value changed: positive = up, negative = down
//   changeUnit   unit of the change, "%" unless you say otherwise
//   changeNote   text after the change, e.g. "vs previous" (optional)
//   changeTone   "good" (green), "bad" (red) or "neutral" (grey).
//                The page decides, because it depends on the KPI:
//                delay going up is bad, speed going up is good.
//   layout       "inline"   change sits to the right of the value
//                "stacked"  change sits on its own line below the value
function KpiTile({
  label,
  value,
  unit,
  change,
  changeUnit = '%',
  changeNote,
  changeTone = 'neutral',
  layout = 'inline',
  className = '',
}) {
  const isUnavailable = value === null || value === undefined
  const hasChange = !isUnavailable && change !== null && change !== undefined

  // 1842 becomes "1,842". Text such as "07:45" is left as it is.
  const displayValue =
    typeof value === 'number' ? value.toLocaleString('en-US') : value

  let arrow = ''
  if (change > 0) arrow = '↑'
  if (change < 0) arrow = '↓'

  return (
    <div className={`kpi-tile kpi-tile-${layout} ${className}`}>
      <p className="kpi-label">{label}</p>

      {isUnavailable ? (
        <p className="kpi-value kpi-value-unavailable">Unavailable</p>
      ) : (
        <p className="kpi-value">
          {displayValue}
          {unit && ` ${unit}`}
        </p>
      )}

      {/* Unavailable tiles show a dash where the change would be */}
      {isUnavailable && <p className="kpi-change kpi-change-neutral">—</p>}

      {hasChange && (
        <p className={`kpi-change kpi-change-${changeTone}`}>
          {arrow} {Math.abs(change)}
          {changeUnit}
          {changeNote && ` ${changeNote}`}
        </p>
      )}
    </div>
  )
}

export default KpiTile