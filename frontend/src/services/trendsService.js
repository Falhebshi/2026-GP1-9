// Where the Traffic Patterns & Trends page gets its data.
//
// For now it returns FAKE data. When the backend is ready, only the inside
// of getTrends() and getBreakdown() changes; the page stays the same, as
// long as the data keeps the shape described here.
//
// Every KPI value is a KpiResult, exactly as the backend's KPI engine
// sends it (data_models.md, section 6): kpi, method, unit, level, the
// element's id, interval_start, interval_end, value, los_grade, status,
// reason, is_shared_value. Display it with src/utils/kpi.js.
// If the API sends a flat list of KpiResults, group them into the shapes
// below HERE, so the page never changes.
//
// Agreed (17 Oct 2026):
//   - The API may send a flat list of KpiResults; this file groups them.
//   - The backend sends the LOS reference lines for the trend chart
//     (trend.referenceLines), from its own parameters, so the chart and
//     the grades can never disagree.
//
// Assumed, NOT yet confirmed by the backend team (if one changes, adjust
// this file only):
//   - Summary results cover the whole period, plus the previous period of
//     the same length for the change. Queue = 95th percentile of cycle maxima.
//   - Daily trend: one value per day, combined from its 15-minute intervals.
//   - Heatmap: average delay and LOS per weekday × hour across the period.
//   - LOS distribution: share of 15-minute intervals at each grade.
//   - Threshold windows, their rules, and "recurring" = exceeded on at
//     least half the days of the period.
//   - Peak congestion window: the 15 minutes with the highest average delay.
//   - Weekdays = Sunday to Thursday, weekends = Friday and Saturday.
//
// ---------------------------------------------------------------------------
// getTrends({ periodDays, dayType, approachId })
//
//   periodDays   7, 30 or 90
//   dayType      'all', 'weekdays' (Sun–Thu) or 'weekends' (Fri–Sat)
//   approachId   'all' or one approach id, e.g. 'east'
//
// gives back:
// {
//   isSample: true,                    only on fake data: shows the banner
//   intersection: { name, area, approaches, signalType },   LocationInfoCard
//   approaches: [{ approach_id, label }],                   Approach filter
//   period: { start, end, intervalCount, runsPerInterval },
//   summary: {                         the KPI row, for the selected element
//     control_delay:            { current: KpiResult, previous: KpiResult },
//     queue_length:             { current, previous, worst: { label, storageRatio: KpiResult } },
//     throughput:               { current, previous },
//     volume_to_capacity_ratio: { current, previous },   peak 15 minutes:
//                                                         interval_start/end = when
//     level_of_service:         { current },
//     peakWindow: { interval_start, interval_end, sameAsPrevious: true },
//   },
//   trend: {                           Performance trend, one point per day
//     metrics: ['control_delay', 'queue_length', 'throughput', 'volume_to_capacity_ratio'],
//     series: { control_delay: [{ date: '2026-09-15', result: KpiResult }, …], … },
//     referenceLines: { control_delay: [{ value: 35, label: 'LOS C/D' }, …] },
//     anomalies: [{ date, label }],
//   },
//   weekdayWeekend: {                  one pair per KPI
//     control_delay: { weekdays: KpiResult, weekends: KpiResult }, …
//   },
//   heatmap: [{ day: 0–6 (0 = Sunday), hour: 0–23, result: KpiResult }],
//                                      result = level of service, with the
//                                      control delay behind it in delay
//   thresholds: {
//     totalDays: 30, recurrenceDays: 15,      recurring = at least recurrenceDays
//     windows: [{ id, start: '07:30', end: '09:00', rule, location, title,
//                 daysExceeded, interventionId }],
//   },
//   losDistribution: [{ element: { level, id, label }, shares: { A: 0.15, … F: 0.05 } }],
//                                      share of 15-minute intervals per grade
//   recurringAlerts: [{ id, title, location, when, daysSeen, daysTotal, rule,
//                       status: 'active', interventionId }],
//   breakdownWindows: [{ id, label }], choices for the breakdown table
// }
//
// ---------------------------------------------------------------------------
// getBreakdown({ periodDays, dayType, approachId, windowId })
//
// gives back the Approach and movement breakdown for one time window:
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

export async function getTrends({ periodDays = 30, dayType = 'all', approachId = 'all' } = {}) {
  await wait(400)
  checkDemo()
  return buildTrends(periodDays, dayType, approachId)
}

export async function getBreakdown({
  periodDays = 30,
  dayType = 'all',
  approachId = 'all',
  windowId = 'pm-peak',
} = {}) {
  await wait(250)
  checkDemo()
  return buildBreakdown(periodDays, dayType, approachId, windowId)
}

// FOR TESTING ONLY: add ?demo=error or ?demo=empty to the page address
function checkDemo() {
  if (typeof window === 'undefined') return
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'error') throw new Error('The analysis service is not responding.')
  if (demo === 'empty') throw new EmptyPeriodError()
}

// Thrown when there is no data at all for the selected period
export class EmptyPeriodError extends Error {
  constructor() {
    super('No performance data is available for the selected period or day type.')
    this.name = 'EmptyPeriodError'
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// ===========================================================================
// Everything below makes the FAKE data. It is deleted when the backend
// arrives. It imitates the backend (including its LOS grading), so the page
// can be built and tested now.
// ===========================================================================

const END_DATE = '2026-10-14' // last day of fake data
const SCENARIO_ID = 'SCN_HIST_BASELINE'
const RUN_IDS = ['RUN_HIST_SEED42']

const INTERSECTION = {
  id: 'INT_IMAM_SAUD_PRINCE_TURKI',
  name: 'Imam Saud Rd × Prince Turki Rd',
  area: 'Al Nakheel',
  approaches: 4,
  signalType: 'Fixed-time, 4 phases, 120 s cycle',
}

// Lane layout from data_models.md (section 2.5). Movement values are the
// fake weekday 17:00–18:00 values; everything else is scaled from them.
const APPROACHES = [
  {
    approach_id: 'east',
    label: 'East',
    movements: [
      { movement_id: 'MOV_E_T', label: 'Through', delay: 38, vc: 0.88, queue: 145, storage: 0.58, duration: 52, flow: 1480, sharedLane: null },
      { movement_id: 'MOV_E_L', label: 'Left', delay: 61, vc: 0.97, queue: 118, storage: 0.98, duration: 74, flow: 310, sharedLane: 'LANE_E_2' },
    ],
  },
  {
    approach_id: 'west',
    label: 'West',
    movements: [
      { movement_id: 'MOV_W_T', label: 'Through', delay: 34, vc: 0.81, queue: 132, storage: 0.53, duration: 48, flow: 1390, sharedLane: null },
      { movement_id: 'MOV_W_L', label: 'Left', delay: 72, vc: 1.04, queue: 126, storage: 1.05, duration: 81, flow: 290, sharedLane: 'LANE_W_2' },
    ],
  },
  {
    approach_id: 'south',
    label: 'South',
    movements: [
      { movement_id: 'MOV_S_T', label: 'Through', delay: 41, vc: 0.9, queue: 160, storage: 0.64, duration: 55, flow: 1120, sharedLane: null },
    ],
  },
  {
    approach_id: 'north',
    label: 'North',
    movements: [
      { movement_id: 'MOV_N_L', label: 'Left', delay: 47, vc: 0.86, queue: 110, storage: 0.73, duration: 63, flow: 880, sharedLane: null },
    ],
  },
]

const CRITICAL_VC = 0.94 // intersection critical v/c (Xc), weekday PM peak

// How much busier or quieter each choice is than the weekday PM peak
const DAY_TYPE_FACTOR = { all: 0.86, weekdays: 0.9, weekends: 0.68 }
const WINDOWS = [
  { id: 'pm-peak', label: '17:00–18:00', factor: 1 },
  { id: 'am-peak', label: '07:30–08:30', factor: 0.9 },
  { id: 'midday', label: '12:00–13:00', factor: 0.7 },
  { id: 'whole-day', label: 'Whole day', factor: 0.6 },
]

// The thresholds the backend uses (HCM 6th edition, signalized)
const LOS_LIMITS = [
  ['A', 10],
  ['B', 20],
  ['C', 35],
  ['D', 55],
  ['E', 80],
]
function gradeFor(delay, vc) {
  if (vc != null && vc > 1) return 'F'
  for (const [grade, limit] of LOS_LIMITS) if (delay <= limit) return grade
  return 'F'
}

// A random number generator that gives the same numbers every time, so the
// fake page looks the same on every reload
function seeded(seed) {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function round(value, decimals = 0) {
  const factor = 10 ** decimals
  return Math.round(value * factor) / factor
}

const UNITS = {
  control_delay: 's/veh',
  level_of_service: 'grade',
  volume_to_capacity_ratio: 'ratio',
  queue_length: 'm',
  queue_storage_ratio: 'ratio',
  queue_duration: 's',
  throughput: 'veh/h',
}
const METHODS = { volume_to_capacity_ratio: 'hcm' } // everything else: simulation

// One KpiResult, shaped like the backend's
function result(kpi, value, element, interval, extra = {}) {
  const base = {
    kpi,
    method: METHODS[kpi] ?? 'simulation',
    unit: UNITS[kpi],
    level: element.level,
    [`${element.level}_id`]: element.id,
    interval_start: interval[0],
    interval_end: interval[1],
    value: kpi === 'level_of_service' ? null : value,
    los_grade: null,
    status: 'ok',
    reason: null,
    scenario_id: SCENARIO_ID,
    run_ids: RUN_IDS,
    is_shared_value: false,
    ...extra,
  }
  if (kpi === 'level_of_service') base.los_grade = value
  return base
}

function unavailable(kpi, element, interval, reason) {
  return result(kpi, null, element, interval, { value: null, status: 'unavailable', reason })
}

function dateString(date) {
  return date.toISOString().slice(0, 10)
}

function addDays(dateText, days) {
  const date = new Date(`${dateText}T00:00:00Z`)
  date.setUTCDate(date.getUTCDate() + days)
  return dateString(date)
}

function stamp(dateText, time) {
  return `${dateText}T${time}:00+03:00`
}

function isWeekend(dateText) {
  const day = new Date(`${dateText}T00:00:00Z`).getUTCDay() // 0 = Sunday
  return day === 5 || day === 6 // Friday, Saturday
}

function matchesDayType(dateText, dayType) {
  if (dayType === 'weekdays') return !isWeekend(dateText)
  if (dayType === 'weekends') return isWeekend(dateText)
  return true
}

// The KPI values of every approach and the intersection, scaled by a factor
function elementValues(factor) {
  const delayScale = factor
  const flowScale = 0.55 + 0.45 * factor

  const approaches = APPROACHES.map((approach) => {
    const movements = approach.movements.map((m) => {
      const vc = round(m.vc * (0.6 + 0.4 * factor), 2)
      const delay = round(m.delay * delayScale)
      return {
        ...m,
        delay,
        vc,
        grade: gradeFor(delay, vc),
        queue: round(m.queue * (0.4 + 0.6 * factor)),
        storage: round(m.storage * (0.4 + 0.6 * factor), 2),
        duration: round(m.duration * delayScale),
        flow: round(m.flow * flowScale, -1),
      }
    })
    // Roll-up rules from the KPI engine: delay flow-weighted, throughput
    // summed, v/c and queue measures take the worst movement
    const flow = movements.reduce((sum, m) => sum + m.flow, 0)
    const delay = round(movements.reduce((sum, m) => sum + m.delay * m.flow, 0) / flow)
    return {
      ...approach,
      movements,
      delay,
      grade: gradeFor(delay),
      vc: Math.max(...movements.map((m) => m.vc)),
      queue: Math.max(...movements.map((m) => m.queue)),
      storage: Math.max(...movements.map((m) => m.storage)),
      duration: Math.max(...movements.map((m) => m.duration)),
      flow,
    }
  })

  const flow = approaches.reduce((sum, a) => sum + a.flow, 0)
  const delay = round(approaches.reduce((sum, a) => sum + a.delay * a.flow, 0) / flow)
  const intersection = {
    delay,
    grade: gradeFor(delay),
    vc: round(CRITICAL_VC * (0.6 + 0.4 * factor), 2),
    queue: Math.max(...approaches.map((a) => a.queue)),
    storage: Math.max(...approaches.map((a) => a.storage)),
    duration: Math.max(...approaches.map((a) => a.duration)),
    flow,
  }
  return { approaches, intersection }
}

function resultsFor(values, element, interval, sharedLane) {
  const shared = sharedLane
    ? { is_shared_value: true, measured_on_lane_id: sharedLane }
    : {}
  return {
    control_delay: result('control_delay', values.delay, element, interval),
    level_of_service: result('level_of_service', values.grade, element, interval),
    volume_to_capacity_ratio: result('volume_to_capacity_ratio', values.vc, element, interval),
    queue_length: result('queue_length', values.queue, element, interval, shared),
    queue_storage_ratio: result('queue_storage_ratio', values.storage, element, interval, shared),
    queue_duration: result('queue_duration', values.duration, element, interval),
    throughput: result('throughput', values.flow, element, interval),
  }
}

function buildBreakdown(periodDays, dayType, approachId, windowId) {
  const window = WINDOWS.find((w) => w.id === windowId) ?? WINDOWS[0]
  const values = elementValues(window.factor * DAY_TYPE_FACTOR[dayType])
  const end = END_DATE
  const start = addDays(end, -(periodDays - 1))
  const interval = [stamp(start, '00:00'), stamp(addDays(end, 1), '00:00')]

  const approaches = values.approaches
    .filter((a) => approachId === 'all' || a.approach_id === approachId)
    .map((a) => ({
      approach_id: a.approach_id,
      label: a.label,
      results: resultsFor(a, { level: 'approach', id: a.approach_id }, interval),
      movements: a.movements.map((m) => ({
        movement_id: m.movement_id,
        label: m.label,
        results: resultsFor(m, { level: 'movement', id: m.movement_id }, interval, m.sharedLane),
      })),
    }))

  return {
    window: { id: window.id, label: window.label },
    approaches,
    intersection: {
      results: resultsFor(values.intersection, { level: 'intersection', id: INTERSECTION.id }, interval),
    },
  }
}

function buildTrends(periodDays, dayType, approachId) {
  const random = seeded(periodDays * 31 + dayType.length * 7 + approachId.length)
  const end = END_DATE
  const start = addDays(end, -(periodDays - 1))
  const period = [stamp(start, '00:00'), stamp(addDays(end, 1), '00:00')]

  const selected =
    approachId === 'all'
      ? { level: 'intersection', id: INTERSECTION.id, label: 'Intersection' }
      : { level: 'approach', id: approachId, label: APPROACHES.find((a) => a.approach_id === approachId)?.label }

  // Average over the period, and the period before it (slightly better)
  const averageFactor = 0.74 * DAY_TYPE_FACTOR[dayType]
  const now = elementValues(averageFactor)
  const before = elementValues(averageFactor * 0.96)
  const pick = (values) =>
    approachId === 'all' ? values.intersection : values.approaches.find((a) => a.approach_id === approachId)
  const cur = pick(now)
  const prev = pick(before)
  const previousPeriod = [stamp(addDays(start, -periodDays), '00:00'), period[0]]

  // Worst queue: the approach (or movement) that has the longest queue
  const worstPool = approachId === 'all' ? now.approaches.flatMap((a) => a.movements.map((m) => ({ ...m, approachLabel: a.label }))) : pick(now).movements.map((m) => ({ ...m, approachLabel: pick(now).label }))
  const worst = worstPool.reduce((a, b) => (b.queue > a.queue ? b : a))

  // Peak 15 minutes for v/c: weekdays 17:15–17:30 on the last weekday
  const peakDay = isWeekend(end) ? addDays(end, -2) : end
  const peakInterval = dayType === 'weekends'
    ? [stamp(end, '20:15'), stamp(end, '20:30')]
    : [stamp(peakDay, '17:15'), stamp(peakDay, '17:30')]
  const peak = pick(elementValues(DAY_TYPE_FACTOR[dayType] * 1.05))
  const peakBefore = pick(elementValues(DAY_TYPE_FACTOR[dayType] * 1.02))

  const summary = {
    control_delay: {
      current: result('control_delay', cur.delay, selected, period),
      previous: result('control_delay', prev.delay, selected, previousPeriod),
    },
    queue_length: {
      current: result('queue_length', worst.queue, selected, period),
      previous: result('queue_length', round(worst.queue * 0.94), selected, previousPeriod),
      worst: {
        label: `${worst.approachLabel} ${worst.label.toLowerCase()}`,
        storageRatio: result('queue_storage_ratio', worst.storage, { level: 'movement', id: worst.movement_id }, period),
      },
    },
    throughput: {
      current: result('throughput', cur.flow, selected, period),
      previous: result('throughput', round(prev.flow * 0.97, -1), selected, previousPeriod),
    },
    volume_to_capacity_ratio: {
      current: result('volume_to_capacity_ratio', peak.vc, selected, peakInterval),
      previous: result('volume_to_capacity_ratio', peakBefore.vc, selected, previousPeriod),
    },
    level_of_service: {
      current: result('level_of_service', cur.grade, selected, period),
    },
    peakWindow: {
      interval_start: peakInterval[0],
      interval_end: peakInterval[1],
      sameAsPrevious: true,
    },
  }

  // ---- Performance trend: one point per day -------------------------------
  const days = []
  for (let i = 0; i < periodDays; i++) {
    const date = addDays(start, i)
    if (matchesDayType(date, dayType)) days.push(date)
  }
  const anomalyDate = days[Math.floor(days.length * 0.6)]
  const missingDate = periodDays >= 30 ? days[Math.floor(days.length * 0.25)] : null

  const series = { control_delay: [], queue_length: [], throughput: [], volume_to_capacity_ratio: [] }
  for (const date of days) {
    const dayInterval = [stamp(date, '00:00'), stamp(addDays(date, 1), '00:00')]
    if (date === missingDate) {
      const reason = 'Simulation run failed for this day.'
      for (const kpi of Object.keys(series)) {
        series[kpi].push({ date, result: unavailable(kpi, selected, dayInterval, reason) })
      }
      continue
    }
    const weekendDip = isWeekend(date) ? 0.72 : 1
    const spike = date === anomalyDate ? 1.3 : 1
    const wobble = 0.9 + random() * 0.2
    const f = averageFactor * weekendDip * spike * wobble / DAY_TYPE_FACTOR[dayType] * DAY_TYPE_FACTOR.weekdays
    const day = pick(elementValues(f))
    series.control_delay.push({ date, result: result('control_delay', day.delay, selected, dayInterval) })
    series.queue_length.push({ date, result: result('queue_length', day.queue, selected, dayInterval) })
    series.throughput.push({ date, result: result('throughput', day.flow, selected, dayInterval) })
    series.volume_to_capacity_ratio.push({ date, result: result('volume_to_capacity_ratio', day.vc, selected, dayInterval) })
  }

  const trend = {
    metrics: Object.keys(series),
    series,
    referenceLines: {
      control_delay: [
        { value: 35, label: 'LOS C/D' },
        { value: 55, label: 'LOS D/E' },
      ],
      volume_to_capacity_ratio: [{ value: 1, label: 'Capacity' }],
    },
    anomalies: anomalyDate ? [{ date: anomalyDate, label: 'Anomaly day' }] : [],
  }

  // ---- Weekdays vs weekends ------------------------------------------------
  const wd = pick(elementValues(0.74 * DAY_TYPE_FACTOR.weekdays))
  const we = pick(elementValues(0.74 * DAY_TYPE_FACTOR.weekends))
  const weekdayWeekend = {}
  for (const [kpi, field] of [
    ['control_delay', 'delay'],
    ['queue_length', 'queue'],
    ['throughput', 'flow'],
    ['volume_to_capacity_ratio', 'vc'],
  ]) {
    weekdayWeekend[kpi] = {
      weekdays: result(kpi, wd[field], selected, period),
      weekends: result(kpi, we[field], selected, period),
    }
  }

  // ---- Congestion by hour and day -----------------------------------------
  // How busy each hour is, from night (low) to the evening peak (high)
  const weekdayProfile = [0.25, 0.2, 0.18, 0.18, 0.2, 0.35, 0.7, 1.15, 1.0, 0.75, 0.65, 0.7, 0.85, 0.85, 0.8, 0.9, 1.05, 1.35, 1.25, 0.9, 0.75, 0.6, 0.45, 0.35]
  const weekendProfile = [0.4, 0.3, 0.25, 0.2, 0.2, 0.22, 0.3, 0.4, 0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.85, 0.85, 0.9, 0.95, 1.0, 1.05, 1.0, 0.9, 0.75, 0.55]
  const heatmap = []
  for (let day = 0; day < 7; day++) {
    const weekend = day === 5 || day === 6
    const profile = weekend ? weekendProfile : weekdayProfile
    for (let hour = 0; hour < 24; hour++) {
      const hourText = String(hour).padStart(2, '0')
      const interval = [stamp(start, `${hourText}:00`), stamp(start, `${hourText}:59`)]
      const shown = dayType === 'all' || (dayType === 'weekends') === weekend
      if (!shown) {
        heatmap.push({ day, hour, result: unavailable('level_of_service', selected, interval, 'Not part of the selected day type.') })
        continue
      }
      const v = pick(elementValues(profile[hour] * (0.95 + random() * 0.1)))
      heatmap.push({
        day,
        hour,
        result: result('level_of_service', v.grade, selected, interval),
        delay: result('control_delay', v.delay, selected, interval),
      })
    }
  }

  // ---- Threshold exceedance and recurring alerts --------------------------
  const share = (days30) => Math.round((days30 / 30) * days.length)
  const totalDays = days.length
  const recurrenceDays = Math.ceil(totalDays / 2)
  const dayWord = dayType === 'weekends' ? 'Weekends' : dayType === 'weekdays' ? 'Weekdays' : 'Weekdays'
  const windows = [
    { id: 'w1', start: '06:00', end: '07:00', rule: 'Control delay > 55 s', location: 'Intersection', title: 'Early delay at LOS E', daysExceeded: share(3), interventionId: null },
    { id: 'w2', start: '07:30', end: '09:00', rule: 'Control delay > 55 s', location: 'Intersection', title: 'Morning peak delay at LOS E', daysExceeded: share(17), interventionId: 2 },
    { id: 'w3', start: '12:00', end: '15:00', rule: 'v/c ≥ 0.90', location: 'East approach · left', title: 'East left near capacity', daysExceeded: share(16), interventionId: 3 },
    { id: 'w4', start: '16:30', end: '19:00', rule: 'Storage ratio ≥ 1.0', location: 'West approach · left', title: 'Left-turn queue overflows its storage', daysExceeded: share(22), interventionId: 1 },
    { id: 'w5', start: '20:00', end: '22:00', rule: 'Control delay > 55 s', location: 'Intersection', title: 'Evening delay at LOS E', daysExceeded: share(9), interventionId: null },
  ].filter((w) => approachId === 'all' || w.location === 'Intersection' || w.location.toLowerCase().startsWith(approachId))

  const recurringAlerts = windows
    .filter((w) => w.daysExceeded >= recurrenceDays)
    .sort((a, b) => b.daysExceeded - a.daysExceeded)
    .map((w) => ({
      id: `ra-${w.id}`,
      title: w.title,
      location: w.location,
      when: `${dayWord}, ${w.start}–${w.end}`,
      daysSeen: w.daysExceeded,
      daysTotal: totalDays,
      rule: w.rule,
      status: 'active',
      interventionId: w.interventionId,
    }))

  // ---- Level of service distribution --------------------------------------
  const losShares = {
    intersection: [0.18, 0.27, 0.3, 0.13, 0.08, 0.04],
    east: [0.17, 0.26, 0.3, 0.16, 0.08, 0.03],
    west: [0.12, 0.24, 0.27, 0.19, 0.11, 0.07],
    south: [0.2, 0.27, 0.27, 0.16, 0.07, 0.03],
    north: [0.18, 0.25, 0.31, 0.16, 0.07, 0.03],
  }
  const tilt = dayType === 'weekends' ? -0.04 : dayType === 'weekdays' ? 0.02 : 0
  const losDistribution = [
    { level: 'intersection', id: INTERSECTION.id, label: 'Intersection', key: 'intersection' },
    ...APPROACHES.map((a) => ({ level: 'approach', id: a.approach_id, label: a.label, key: a.approach_id })),
  ]
    .filter((e) => approachId === 'all' || e.level === 'intersection' || e.id === approachId)
    .map((e) => {
      const raw = losShares[e.key].map((s, i) => Math.max(0.01, s + (i < 2 ? -tilt : tilt / 2)))
      const total = raw.reduce((a, b) => a + b, 0)
      const shares = {}
      ;['A', 'B', 'C', 'D', 'E', 'F'].forEach((g, i) => {
        shares[g] = round(raw[i] / total, 3)
      })
      return { element: { level: e.level, id: e.id, label: e.label }, shares }
    })

  return {
    isSample: true,
    intersection: {
      name: INTERSECTION.name,
      area: INTERSECTION.area,
      approaches: INTERSECTION.approaches,
      signalType: INTERSECTION.signalType,
    },
    approaches: APPROACHES.map((a) => ({ approach_id: a.approach_id, label: a.label })),
    period: {
      start,
      end,
      intervalCount: days.length * 96,
      runsPerInterval: RUN_IDS.length,
    },
    summary,
    trend,
    weekdayWeekend,
    heatmap,
    thresholds: { totalDays, recurrenceDays, windows },
    losDistribution,
    recurringAlerts,
    breakdownWindows: WINDOWS.map((w) => ({ id: w.id, label: w.label })),
  }
}