import { INTERSECTION_KPIS, KPI_DEFINITIONS, METHOD_LABELS } from './kpi'

// What a group of KPIs shares, said once for the whole group (KpiGroup, KpiSummary): what the
// changes are compared with and how the values were measured. Pages show these sentences behind
// an info button.

// The sentences a group of KPIs shares: the comparison, then the method
export function kpiNotes(compared, results = []) {
  const methods = methodLine(results)
  return [compared && `Changes compared with ${compared}`, methods].filter(Boolean)
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

// The intersection's KPIs on Current Traffic and Traffic Forecast (KpiSummary): the level of
// service, then the tiles (see INTERSECTION_KPIS)
const TILES = INTERSECTION_KPIS.filter((kpi) => kpi !== 'level_of_service')

export const losOf = (kpis) => kpis.find((k) => k.current.kpi === 'level_of_service')?.current

export const summaryTiles = (kpis) =>
  TILES.map((kpi) => kpis.find((k) => k.current.kpi === kpi)).filter(Boolean)

export function summaryResults(kpis) {
  const los = losOf(kpis)
  return [...(los ? [los] : []), ...summaryTiles(kpis).map(({ current }) => current)]
}

// The comparison and method sentences of the intersection's KPIs, for a card header
export function summaryNotes(kpis, compared) {
  return kpiNotes(compared, summaryResults(kpis))
}
