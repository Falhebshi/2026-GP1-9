// Where the Traffic Patterns & Trends page gets its data.
//
// The data are files written by the backend's historical analysis
// (docs/kpi_engine.md, section 17), one per period and day type:
//
//   /data/<intersection>/history/trends_<7|30|90>d_<all|weekdays|weekends>.json
//
// Every KPI value is a KpiResult, exactly as the backend's KPI engine
// writes it (data_models.md, section 6): kpi, method, unit, level, the
// element's id, interval_start, interval_end, value, los_grade, status,
// reason, is_shared_value. Display it with src/utils/kpi.js. The results
// combine one simulated day per run (run_combination 'days'), so they have
// no standard deviation.
//
// The files are compact: the fields every result shares are written once,
// as resultDefaults, and each result leaves out its null fields and the
// fields equal to their default. unpack() below puts them back, so the
// page only ever sees complete KpiResults.
//
// ---------------------------------------------------------------------------
// getTrends({ periodDays, dayType, approachId })
//
//   periodDays   7, 30 or 90 (the last days up to the latest simulated day)
//   dayType      'all', 'weekdays' (Sun–Thu) or 'weekends' (Fri–Sat)
//   approachId   'all' or one approach id, e.g. 'APP_E'
//
// gives back:
// {
//   intersection: { name, area, approaches, signalType },   LocationInfoCard
//   approaches: [{ approach_id, label }],                   Approach filter
//   period: { start, end, dayType, daysExpected, daysUsed, missingDays,
//             intervalCount, runsPerInterval },
//   summary: {                         the KPI row, for the selected element
//     control_delay:            { current: KpiResult },
//     level_of_service:         { current },
//     throughput:               { current },
//     volume_to_capacity_ratio: { current },   the peak 15 minutes:
//                                               interval_start/end = when
//     queue_length:             { current, worst: { movement_id, label, storageRatio } | null },
//                                               worst is null when a movement's
//                                               queue is unavailable
//     peakWindow: { status, reason, interval_start, interval_end },
//                                               the usual 15 minutes with the
//                                               highest delay; unknown when a
//                                               slot's delay is unavailable
//   },
//   trend: {                           one point per day
//     metrics: ['control_delay', 'queue_length', 'throughput', 'volume_to_capacity_ratio'],
//     series: { control_delay: [{ date: '2026-11-03', result: KpiResult }, …], … },
//     referenceLines: { control_delay: [{ value: 35, label: 'LOS C/D' }, …] },
//     anomalies: [],                   not produced yet
//   },
//   weekdayWeekend: { control_delay: { weekdays: KpiResult, weekends: KpiResult }, … },
//   heatmap: [{ day: 0–6 (0 = Sunday), hour: 0–23, result: KpiResult, delay: KpiResult }],
//   losDistribution: [{ element: { level, id, label }, intervals,
//                       shares: { A … F, unavailable } }],
//                                      share of 15-minute intervals per grade,
//                                      and the share whose grade is unknown
//   recurringAlerts: null,             not available yet (backlog items 24–25)
//   thresholds: null,                  not available yet (backlog items 24–25)
//   breakdownWindows: [{ id: 'whole-day', label: 'Whole day', default: true }],
//                                      any single hour is also available
//                                      through the table's hour picker
// }
//
// Throws EmptyPeriodError, with the backend's reason, when the period has
// too few simulated days (for example "not enough data: 14 of 30 days are
// stored (at least 24 are needed)").
//
// ---------------------------------------------------------------------------
// getBreakdown({ periodDays, dayType, approachId, windowId })
//
// gives back the Approach and movement breakdown for one time window.
// windowId is 'whole-day' or a single hour written 'hour-HH' (e.g.
// 'hour-17' = 17:00–18:00).
// {
//   window: { id, label },
//   approaches: [{ approach_id, label, results: RESULTS,
//                  movements: [{ movement_id, label, results: RESULTS }] }],
//   intersection: { results: RESULTS },
// }
// where RESULTS = { control_delay, level_of_service, volume_to_capacity_ratio,
//                   queue_length, queue_storage_ratio, queue_duration,
//                   throughput }, each a KpiResult.
// ---------------------------------------------------------------------------

const INTERSECTION_ID = 'INT_001'
const DATA_FOLDER = '/data'
const WHOLE_DAY = 'whole-day'

// Same words as Current Traffic (currentTrafficService.js): one signal program
const SIGNAL_TYPE = 'Fixed-time, 120 s cycle'

export async function getTrends({ periodDays = 7, dayType = 'all', approachId = 'all' } = {}) {
  checkDemo()
  const file = await loadTrendsFile(periodDays, dayType)
  const view = file.views[approachId] ?? file.views.all
  const intersection = await loadIntersection(file)

  return {
    intersection,
    approaches: file.approaches,
    period: file.period,
    summary: view.summary,
    trend: view.trend,
    weekdayWeekend: view.weekdayWeekend,
    heatmap: view.heatmap,
    losDistribution: file.losDistribution.filter(
      (row) => approachId === 'all' || row.element.level === 'intersection' || row.element.id === approachId,
    ),
    recurringAlerts: null,
    thresholds: null,
    breakdownWindows: file.breakdownWindows.filter((w) => w.id === WHOLE_DAY),
  }
}

export async function getBreakdown({
  periodDays = 7,
  dayType = 'all',
  approachId = 'all',
  windowId = WHOLE_DAY,
} = {}) {
  checkDemo()
  const file = await loadTrendsFile(periodDays, dayType)
  const breakdown = file.breakdown[windowId]
  if (!breakdown) throw new Error(`There is no breakdown for the time window "${windowId}".`)

  return {
    ...breakdown,
    approaches: breakdown.approaches.filter((a) => approachId === 'all' || a.approach_id === approachId),
  }
}

// Thrown when the selected period has too few simulated days
export class EmptyPeriodError extends Error {
  constructor(message = 'No performance data is available for the selected period or day type.') {
    super(message)
    this.name = 'EmptyPeriodError'
  }
}

// FOR TESTING ONLY: add ?demo=error or ?demo=empty to the page address
function checkDemo() {
  if (typeof window === 'undefined') return
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'error') throw new Error('The analysis service is not responding.')
  if (demo === 'empty') throw new EmptyPeriodError()
}

// ---------------------------------------------------------------------------
// Loading and unpacking
// ---------------------------------------------------------------------------

// Files already loaded, so the breakdown table does not load its file again
const loaded = new Map()

async function loadTrendsFile(periodDays, dayType) {
  const name = `trends_${periodDays}d_${dayType}.json`

  if (!loaded.has(name)) {
    loaded.set(
      name,
      getJson(`${DATA_FOLDER}/${INTERSECTION_ID}/history/${name}`).then((file) =>
        file.available ? unpack(file, file.resultDefaults) : file,
      ),
    )
  }

  const file = await loaded.get(name).catch((err) => {
    loaded.delete(name) // let the next attempt load it again
    throw err
  })
  if (!file.available) throw new EmptyPeriodError(sentence(file.reason))
  return file
}

// The KpiResult fields that can be left out of a compact result because
// they are null (or, for input_origins, empty)
const NULL_FIELDS = {
  lane_id: null,
  lane_group_id: null,
  movement_id: null,
  approach_id: null,
  intersection_id: null,
  measured_on_lane_id: null,
  measured_on_lane_group_id: null,
  uncontrolled_movements: null,
  value: null,
  los_grade: null,
  reason: null,
  standard_deviation: null,
  value_computation: null,
  input_origins: [],
}

// Every compact result inside the file, back in full: the null fields,
// then the file's defaults, then the result's own fields
export function unpack(item, defaults) {
  if (Array.isArray(item)) return item.map((value) => unpack(value, defaults))
  if (item === null || typeof item !== 'object') return item
  if (isResult(item)) return { ...NULL_FIELDS, ...defaults, ...item }

  const out = {}
  for (const [key, value] of Object.entries(item)) out[key] = unpack(value, defaults)
  return out
}

function isResult(item) {
  return 'kpi' in item && 'status' in item && 'interval_start' in item
}

async function loadIntersection(file) {
  const list = await getJson(`${DATA_FOLDER}/intersections.json`).catch(() => [])
  const found = list.find((i) => i.intersection_id === INTERSECTION_ID)

  return {
    name: found?.name_en,
    area: found?.area_label,
    approaches: file.approaches.length,
    signalType: SIGNAL_TYPE,
  }
}

async function getJson(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`The performance data could not be loaded (${response.status}).`)
  return response.json()
}

// "not enough data: 14 of 30 …" → "Not enough data: 14 of 30 …."
function sentence(text) {
  if (!text) return undefined
  const first = text.charAt(0).toUpperCase() + text.slice(1)
  return first.endsWith('.') ? first : `${first}.`
}
