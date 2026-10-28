import { KPI_DEFINITIONS, METHOD_LABELS } from '../utils/kpi'
import './KpiGroup.css'

// A group of KpiTiles with what they share said once instead of on every tile: what the
// changes are compared with (above) and how the values were measured (below).
//
//   compared   e.g. "the 15 minutes before" gives "Changes compared with the 15 minutes before"
//   results    the KpiResults shown, for the method line
//              ("All simulated except v/c ratio (HCM)")
//   children   the tiles
function KpiGroup({ compared, results = [], children }) {
  const methods = methodLine(results)

  return (
    <div className="kpi-group">
      {compared && <p className="kpi-group-note">Changes compared with {compared}</p>}
      {children}
      {methods && <p className="kpi-group-note">{methods}</p>}
    </div>
  )
}

// The method most results share, then the ones that differ
function methodLine(results) {
  const measured = results.filter((result) => METHOD_LABELS[result?.method])
  if (!measured.length) return ''

  const counts = {}
  measured.forEach(({ method }) => (counts[method] = (counts[method] ?? 0) + 1))
  const main = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0]
  const others = measured
    .filter(({ method }) => method !== main)
    .map(({ kpi, method }) => `${KPI_DEFINITIONS[kpi].label} (${METHOD_LABELS[method]})`)

  const all = `All ${METHOD_LABELS[main].toLowerCase()}`
  return others.length ? `${all} except ${others.join(', ')}` : all
}

export default KpiGroup
