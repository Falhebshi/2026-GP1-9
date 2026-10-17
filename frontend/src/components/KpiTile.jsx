import { STATUS_LABELS } from '../utils/kpi'
import './KpiTile.css'

// One KPI: a label, a value with its unit, and how much it changed.
//
//   label        name of the KPI, e.g. "Control delay"
//   value        a number or text. Leave it out (or pass null) when the KPI
//                has no valid result: the tile then shows "Unavailable"
//                instead of a misleading 0.
//   unit         e.g. "s", "m", "km/h" (optional, for unitless KPIs)
//   decimals     digits after the decimal point for a number (optional)
//   status       'unavailable' or 'not_applicable': which word to show when
//                there is no value ('unavailable' unless you say otherwise)
//   reason       why there is no value, shown in small text under the word
//   detail       a small grey line under the value, e.g. "LOS C" (optional)
//   tag          a small label in the top right corner, e.g. "Simulated"
//                (optional)
//   change       how much the value changed: positive = up, negative = down
//   changeUnit   unit of the change, "%" unless you say otherwise
//   changeNote   text after the change, e.g. "vs previous". Shown on its own
//                when there is no number, e.g. "Same window as before".
//   changeTone   "good" (green), "bad" (red) or "neutral" (grey).
//                The page decides, because it depends on the KPI:
//                delay going up is bad, speed going up is good.
//   layout       "inline"   change sits to the right of the value
//                "stacked"  change sits at the bottom of the tile.
//
// Stacked tiles placed inside <div className="kpi-row"> line up with each
// other row by row: labels, values, details and changes each share a line
// across all the tiles, even when one label wraps onto two lines.
//
// A KPI result from the backend can fill most of these at once:
//   <KpiTile label="Avg control delay" {...kpiTileProps(result)} />
// (kpiTileProps is in src/utils/kpi.js)
function KpiTile({
  label,
  value,
  unit,
  decimals,
  status,
  reason,
  detail,
  tag,
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
    typeof value === 'number'
      ? value.toLocaleString('en-US', {
          minimumFractionDigits: decimals,
          maximumFractionDigits: decimals ?? 3,
        })
      : value

  let arrow = ''
  if (change > 0) arrow = '↑'
  if (change < 0) arrow = '↓'

  let changeLine = null
  if (isUnavailable) {
    // Unavailable tiles show a dash where the change would be
    changeLine = <p className="kpi-change kpi-change-neutral">—</p>
  } else if (hasChange) {
    changeLine = (
      <p className={`kpi-change kpi-change-${changeTone}`}>
        {arrow} {Math.abs(change)}
        {changeUnit}
        {changeNote && ` ${changeNote}`}
      </p>
    )
  } else if (changeNote) {
    changeLine = <p className="kpi-change kpi-change-neutral">{changeNote}</p>
  }

  return (
    <div className={`kpi-tile kpi-tile-${layout} ${className}`}>
      <div className="kpi-head">
        <p className="kpi-label">{label}</p>
        {tag && <span className="kpi-tag">{tag}</span>}
      </div>

      {isUnavailable ? (
        <p className="kpi-value kpi-value-unavailable">
          {STATUS_LABELS[status] ?? STATUS_LABELS.unavailable}
        </p>
      ) : (
        <p className="kpi-value">
          {displayValue}
          {unit && <span className="kpi-unit"> {unit}</span>}
        </p>
      )}

      {layout === 'inline' && changeLine}

      {/* The detail line, and why there is no value. In a stacked tile this
          box is always there, even when empty, so tiles in a kpi-row keep
          the same rows. */}
      {(layout === 'stacked' || detail || (isUnavailable && reason)) && (
        <div className="kpi-info">
          {detail && <p className="kpi-detail">{detail}</p>}
          {isUnavailable && reason && <p className="kpi-reason">{reason}</p>}
        </div>
      )}

      {/* Stacked: the change sits at the bottom of the tile */}
      {layout === 'stacked' && <div className="kpi-footer">{changeLine}</div>}
    </div>
  )
}

export default KpiTile