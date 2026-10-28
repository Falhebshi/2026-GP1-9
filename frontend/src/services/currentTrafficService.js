// Where the Current Traffic page gets its data.
//
// The page shows the simulated run in public/data/<intersection>/baseline/ (the only real data in
// Sprint 1): the run (run.json), its KPI results (kpis.json, KpiResult records from the KPI
// engine) and the approaches (network/approaches.json). The alerts are still sample data.
// getCurrentTraffic() gives back:
//
//   {
//     source: 'run',                     'run' for a simulated run; 'live' once live data exists
//     intersection: { id, center, bounds, name, area, approaches, signalType },
//     run: { id, status, failureReason, start, duration, intervalSeconds },
//                                        null when there is no run yet. status 'completed' or
//                                        'failed' (then failureReason says why, and there are no
//                                        intervals). start: the start of the analysis period (ISO
//                                        time); duration and intervalSeconds in seconds
//     hasKpis: false when the run has no KPI results yet (no kpis.json, or one of another run)
//     intervals: [{                      one per 15 minutes of the analysis period, oldest first
//       start, end,                      ISO times
//       kpis: [{ current: KpiResult, previous: KpiResult }],   intersection level; previous is
//                                        the interval before in the same run (null for the first)
//       approaches: [{
//         approach_id, arm, road,
//         kpis: { <kpi name>: KpiResult },                    approach level
//         movements: [{ movement_id, label, kpis: { <kpi name>: KpiResult } }],
//       }],
//     }],
//     timeline: [{ time, value, level }],      one bar per interval, from the intersection's delay
//     alerts: [{ id, title, details: [{ label, value }], detailsTo }],
//   }
//
// Every KPI value is a KpiResult, exactly as the backend's KPI engine sends it (data_models.md,
// section 6). Pages show them with src/utils/kpi.js. This file never calculates a KPI.

import { notApplicableResult, sampleResult } from './sampleKpiResults'

// The study intersection. Its name, area and centre come from its record in
// public/data/intersections.json, a copy of data/processed/intersections.json.
const INTERSECTION_ID = 'INT_001'

// Half the width of the square that is shown around the centre, in metres. 350 m is just inside
// the shortest main road in the network (Turki Rd going north-west ends at about 359 m), so every
// main road reaches the edge and they are all cut at the same line.
const HALF_SIZE_M = 350
const M_PER_DEG_LAT = 110540

// The square around the centre; nothing outside it is drawn
function squareAround([longitude, latitude]) {
  const mPerDegLon = 111320 * Math.cos((latitude * Math.PI) / 180)
  return {
    west: longitude - HALF_SIZE_M / mPerDegLon,
    east: longitude + HALF_SIZE_M / mPerDegLon,
    south: latitude - HALF_SIZE_M / M_PER_DEG_LAT,
    north: latitude + HALF_SIZE_M / M_PER_DEG_LAT,
  }
}

// Sample data until the backend API is ready

const QUARTER_HOUR = 15 * 60 * 1000

// One bar per 15 minutes for the last 24 hours (96 bars)
export function sampleTimelineBars(now = Date.now()) {
  const newest = Math.floor(now / QUARTER_HOUR) * QUARTER_HOUR
  const bars = []
  for (let stepsBack = 95; stepsBack >= 0; stepsBack--) {
    const date = new Date(newest - stepsBack * QUARTER_HOUR)
    const hour = date.getHours() + date.getMinutes() / 60
    const morningPeak = 0.7 * Math.exp(-((hour - 7.75) ** 2) / 2.2)
    const eveningPeak = 0.8 * Math.exp(-((hour - 17.5) ** 2) / 4)
    const value = Math.min(1, 0.12 + morningPeak + eveningPeak + 0.04 * Math.sin(hour * 5))
    const level = value > 0.7 ? 'high' : value > 0.4 ? 'moderate' : 'low'
    bars.push({ time: date.toISOString(), value, level })
  }
  return bars
}

// Click an alert to see where and when it was detected, like the Forecast Alerts
const SAMPLE_ALERTS = [
  {
    id: 'a1',
    title: 'Queue spillback',
    details: [
      { label: 'Location', value: 'North approach' },
      { label: 'Detected', value: '2 min ago' },
    ],
    detailsTo: '/alerts/1',
  },
  {
    id: 'a2',
    title: 'Low average speed',
    details: [
      { label: 'Location', value: 'East approach' },
      { label: 'Detected', value: '7 min ago' },
    ],
    detailsTo: '/alerts/2',
  },
  {
    id: 'a3',
    title: 'High V/C ratio',
    details: [
      { label: 'Location', value: 'West approach' },
      { label: 'Detected', value: '11 min ago' },
    ],
  },
]

// Approaches and their movements. The movements follow the signal plan in the SUMO network:
// East and West have through and left on the signal, South and North are left only. Right turns
// leave before the signal on slip lanes (South to East, West to South and North to West; East has
// none), so the signal measures (LOS, v/c, capacity, saturation flow) don't apply to them. Whether slip lanes get KPIs at all is still open.
// arm is the side of the junction the approach comes from (matches the 3D scene).

// Markers used in the tables below instead of a value
const SLIP = 'slip'
const MOVEMENT_ONLY = 'movement only'
const NOT_APPLICABLE_REASONS = {
  [SLIP]: 'Uncontrolled right turn on a slip lane, signal measures do not apply.',
  [MOVEMENT_ONLY]: 'Saturation flow is reported per lane group and movement, not per approach.',
}

const KPI_ORDER = [
  'control_delay',
  'level_of_service',
  'volume_to_capacity_ratio',
  'capacity',
  'saturation_flow_rate',
  'queue_length',
  'queue_duration',
  'queue_storage_ratio',
  'throughput',
]

// One element's KPIs from a row of sample values in KPI_ORDER.
// sharedLane is set for a movement on a shared lane: its queue values are the lane's values
// (data_models.md, 6.7), so the page can show the "Shared lane" tag.
function sampleKpis(element, interval, values, sharedLane) {
  const results = {}
  KPI_ORDER.forEach((kpi, i) => {
    const value = values[i]
    if (value in NOT_APPLICABLE_REASONS) {
      results[kpi] = notApplicableResult(kpi, element, interval, NOT_APPLICABLE_REASONS[value])
    } else {
      results[kpi] = sampleResult(kpi, value, element, interval)
    }
  })
  if (sharedLane) {
    for (const kpi of ['queue_length', 'queue_storage_ratio']) {
      results[kpi] = { ...results[kpi], is_shared_value: true, measured_on_lane_id: sharedLane }
    }
  }
  return results
}

export function sampleApproaches(interval) {
  const approach = (approach_id, arm, road, values, movements) => ({
    approach_id,
    arm,
    road,
    kpis: sampleKpis({ level: 'approach', id: approach_id }, interval, values),
    movements: movements.map(([movement_id, label, movementValues, sharedLane]) => ({
      movement_id,
      label,
      kpis: sampleKpis({ level: 'movement', id: movement_id }, interval, movementValues, sharedLane),
    })),
  })
  const M = MOVEMENT_ONLY

  // East and West: lane 2 is shared by left and through, so both movements show its queue
  return [
    approach('APP_E', 'East', 'Imam Saud Rd', [52, 'D', 0.94, 1710, M, 142, 38, 0.81, 1540], [
      ['MOV_E_W', 'Through', [44, 'D', 0.88, 1180, 1820, 142, 31, 0.81, 1040], 'LANE_E_2'],
      ['MOV_E_S', 'Left', [71, 'E', 0.94, 530, 1760, 142, 52, 0.81, 500], 'LANE_E_2'],
    ]),
    approach('APP_W', 'West', 'Imam Saud Rd', [41, 'D', 0.83, 1420, M, 109, 29, 0.66, 1290], [
      ['MOV_W_E', 'Through', [36, 'D', 0.79, 960, 1800, 109, 26, 0.66, 760], 'LANE_W_2'],
      ['MOV_W_N', 'Left', [53, 'D', 0.83, 460, 1750, 109, 35, 0.66, 380], 'LANE_W_2'],
      ['MOV_W_S_SLIP', 'Right (slip lane)', [7, SLIP, SLIP, SLIP, SLIP, 15, 4, 0.25, 150]],
    ]),
    approach('APP_S', 'South', 'Prince Turki Rd, service road', [33, 'C', 0.71, 1020, M, 74, 22, 0.52, 720], [
      ['MOV_S_W', 'Left', [33, 'C', 0.71, 1020, 1790, 74, 22, 0.52, 640]],
      ['MOV_S_E_BYPASS', 'Right (slip lane)', [6, SLIP, SLIP, SLIP, SLIP, 12, 3, 0.2, 80]],
    ]),
    approach('APP_N', 'North', 'Prince Turki Rd, service road', [58, 'F', 1.04, 760, M, 168, 61, 1.12, 790], [
      ['MOV_N_E', 'Left', [64, 'F', 1.04, 760, 1740, 168, 61, 1.12, 700]],
      ['MOV_N_W_SLIP', 'Right (slip lane)', [8, SLIP, SLIP, SLIP, SLIP, 18, 5, 0.3, 90]],
    ]),
  ]
}

// The intersection on its own, for pages that only need its name and position.
// id is also the folder of its 3D data in public/data.
export async function getIntersection() {
  const response = await fetch('/data/intersections.json')
  if (!response.ok) throw new Error('The intersection information could not be loaded.')

  const record = (await response.json()).find((i) => i.intersection_id === INTERSECTION_ID)
  if (!record) throw new Error(`${INTERSECTION_ID} is not in intersections.json.`)

  const center = [record.center_longitude, record.center_latitude]
  return {
    id: record.intersection_id,
    center,
    bounds: squareAround(center),
    name: record.name_en,
    area: record.area_label,
    approaches: 4,
    signalType: 'Fixed-time, 120 s cycle', // same signal program as in SUMO
  }
}

// Gives back everything the Current Traffic page shows (see the top of this file)
export async function getCurrentTraffic() {
  const intersection = await getIntersection()

  // FOR TESTING ONLY: add ?demo=error, ?demo=empty, ?demo=no-run, ?demo=failed or
  // ?demo=no-kpis to the page address to see those states.
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'error') throw new Error('The traffic service is not responding.')

  const folder = `/data/${intersection.id}`
  const approaches = await getJson(`${folder}/network/approaches.json`)
  if (!approaches) throw new Error('The approaches could not be loaded.')

  let run = demo === 'no-run' ? null : await getJson(`${folder}/baseline/run.json`)
  if (run && demo === 'failed') {
    run = { ...run, status: 'failed', failure_reason: 'TraCIException: connection closed by SUMO' }
  }
  const page = { source: 'run', intersection, alerts: SAMPLE_ALERTS }

  if (!run || run.status === 'failed') {
    return {
      ...page,
      run: run && {
        id: run.run_id,
        status: 'failed',
        failureReason: run.failure_reason,
        start: run.run_start,
      },
      hasKpis: false,
      intervals: [],
      timeline: [],
    }
  }

  // Only the KPI results of this run; a kpis.json left from another run is not used
  const kpis = demo === 'no-kpis' ? null : await getJson(`${folder}/baseline/kpis.json`)
  const results = kpis?.run_id === run.run_id ? kpis.results : null
  const intervals =
    demo === 'empty' ? [] : groupByInterval(run, results ?? [], approaches.approaches)

  return {
    ...page,
    run: {
      id: run.run_id,
      status: 'completed',
      failureReason: null,
      start: addSeconds(run.run_start, run.analysis_start_s),
      duration: run.analysis_end_s - run.analysis_start_s,
      intervalSeconds: run.interval_s,
    },
    hasKpis: results !== null,
    intervals,
    timeline: intervals.map(timelineBar),
  }
}

// A JSON file, or null when it is not there. The dev server answers a missing file with the
// page itself, so anything that is not JSON counts as missing too.
async function getJson(url) {
  const response = await fetch(url)
  const isJson = response.headers?.get('content-type')?.includes('json') ?? true
  if (!response.ok || !isJson) return null
  return response.json()
}

// An ISO time plus some seconds, as an ISO time
function addSeconds(iso, seconds) {
  return new Date(Date.parse(iso) + seconds * 1000).toISOString()
}

// The words for a movement, from its type: 'Left', 'Through', 'Right (slip lane)'
function movementLabel({ movement_type: type, control }) {
  if (type === 'left') return 'Left'
  if (type === 'through') return 'Through'
  return control === 'uncontrolled' ? 'Right (slip lane)' : 'Right'
}

// The run's analysis period, one entry per 15-minute interval, with its KPI results (none
// when the run has none yet) in the shape the page uses
function groupByInterval(run, results, approaches) {
  const at = (iso) => Date.parse(iso)
  // the results of one element and interval by KPI name, e.g. of('approach', 'APP_E', start)
  const of = (level, id, start) =>
    Object.fromEntries(
      results
        .filter(
          (r) => r.level === level && r[`${level}_id`] === id && at(r.interval_start) === at(start),
        )
        .map((r) => [r.kpi, r]),
    )
  const starts = []
  for (let s = run.analysis_start_s; s < run.analysis_end_s; s += run.interval_s) {
    starts.push(addSeconds(run.run_start, s))
  }

  return starts.map((start, i) => {
    const before = starts[i - 1]
    const intersection = Object.values(of('intersection', run.intersection_id, start))

    return {
      start,
      end: addSeconds(start, run.interval_s),
      kpis: intersection.map((current) => ({
        current,
        previous: before
          ? (of('intersection', run.intersection_id, before)[current.kpi] ?? null)
          : null,
      })),
      approaches: approaches.map((a) => ({
        approach_id: a.approach_id,
        arm: a.side[0].toUpperCase() + a.side.slice(1),
        road: a.road,
        kpis: of('approach', a.approach_id, start),
        movements: a.movements.map((m) => ({
          movement_id: m.movement_id,
          label: movementLabel(m),
          kpis: of('movement', m.movement_id, start),
        })),
      })),
    }
  })
}

// LOS grades by colour of the timeline bar
const BAR_LEVELS = { A: 'low', B: 'low', C: 'low', D: 'moderate', E: 'high', F: 'high' }

// One timeline bar for an interval: its height from the intersection's control delay (80 s/veh,
// where LOS F starts, is a full bar) and its colour from the level of service. No delay, no bar.
function timelineBar({ start, kpis }) {
  const result = (kpi) => kpis.find((k) => k.current.kpi === kpi)?.current
  const delay = result('control_delay')
  const grade = result('level_of_service')?.los_grade

  return {
    time: start,
    value: delay?.status === 'ok' ? Math.min(1, delay.value / 80) : undefined,
    level: BAR_LEVELS[grade],
  }
}
