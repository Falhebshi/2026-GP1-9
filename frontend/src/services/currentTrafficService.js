// Where the Current Traffic page gets its data.
//
// For now it returns SAMPLE data. When the backend is ready, only the inside of
// getCurrentTraffic() changes; the page stays the same as long as the data keeps this shape:
//
//   {
//     isSample: true,                    true while the data is sample data
//     intersection: { id, center, bounds, name, area, approaches, signalType },
//     timeline: [{ time, value, level }],      one bar per 15 minutes, last 24 hours
//     kpis: [{ current: KpiResult, previous: KpiResult }],   intersection level, latest
//                                        15 minutes and the 15 minutes before, for the change
//     alerts: [{ id, title, details: [{ label, value }], interventionsTo }],
//     approaches: [{
//       approach_id, arm, road,
//       kpis: { <kpi name>: KpiResult },                    approach level
//       movements: [{ movement_id, label, kpis: { <kpi name>: KpiResult } }],
//     }],
//   }
//
// Every KPI value is a KpiResult, exactly as the backend's KPI engine sends it (data_models.md,
// section 6). Pages show them with src/utils/kpi.js. This file never calculates a KPI.

import {
  latestInterval,
  notApplicableResult,
  sampleResult,
} from './sampleKpiResults'

const CENTER = [46.633621, 24.735289]

// Half the width of the square that is shown around the centre, in metres. 350 m is just inside
// the shortest main road in the network (Turki Rd going north-west ends at about 359 m), so every
// main road reaches the edge and they are all cut at the same line.
const HALF_SIZE_M = 350
const M_PER_DEG_LAT = 110540
const M_PER_DEG_LON = 111320 * Math.cos((CENTER[1] * Math.PI) / 180)

// id is the folder in public/data, center is where the 3D camera starts
const INTERSECTION = {
  id: 'turki_imamsaud',
  center: CENTER,
  // square around the centre, nothing outside it is drawn
  bounds: {
    west: CENTER[0] - HALF_SIZE_M / M_PER_DEG_LON,
    east: CENTER[0] + HALF_SIZE_M / M_PER_DEG_LON,
    south: CENTER[1] - HALF_SIZE_M / M_PER_DEG_LAT,
    north: CENTER[1] + HALF_SIZE_M / M_PER_DEG_LAT,
  },
  name: 'Prince Turki Al-Awwal Rd × Imam Saud Rd',
  area: 'An Nakheel, Riyadh',
  approaches: 4,
  signalType: 'Fixed-time, 120 s cycle', // same signal program as in SUMO
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

// Intersection KPIs for the tiles: the latest 15 minutes and the 15 minutes before
function sampleIntersectionKpis(interval, previousInterval) {
  const element = { level: 'intersection', id: 'INT_001' }
  const pair = (kpi, now, before) => ({
    current: sampleResult(kpi, now, element, interval),
    previous: sampleResult(kpi, before, element, previousInterval),
  })
  return [
    pair('control_delay', 46, 44),
    pair('queue_length', 128, 114),
    pair('throughput', 1842, 1788),
    pair('volume_to_capacity_ratio', 0.91, 0.87),
    pair('level_of_service', 'D', 'D'),
  ]
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
    interventionsTo: '/recommendations',
  },
  {
    id: 'a2',
    title: 'Low average speed',
    details: [
      { label: 'Location', value: 'East approach' },
      { label: 'Detected', value: '7 min ago' },
    ],
    interventionsTo: '/recommendations',
  },
  {
    id: 'a3',
    title: 'High V/C ratio',
    details: [
      { label: 'Location', value: 'West approach' },
      { label: 'Detected', value: '11 min ago' },
    ],
    interventionsTo: '/recommendations',
  },
]

// Approaches and their movements. The movements follow the signal plan in the SUMO network:
// East and West have through and left on the signal, South is through only and North is left
// only. Right turns leave before the signal on slip lanes (South to East, West to South and
// North to West; East has none), so the signal measures (LOS, v/c, capacity, saturation flow)
// don't apply to them. Whether slip lanes get KPIs at all is still open.
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

function sampleApproaches(interval) {
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
      ['MOV_S_W', 'Through', [33, 'C', 0.71, 1020, 1790, 74, 22, 0.52, 640]],
      ['MOV_S_E_BYPASS', 'Right (slip lane)', [6, SLIP, SLIP, SLIP, SLIP, 12, 3, 0.2, 80]],
    ]),
    approach('APP_N', 'North', 'Prince Turki Rd, service road', [58, 'F', 1.04, 760, M, 168, 61, 1.12, 790], [
      ['MOV_N_E', 'Left', [64, 'F', 1.04, 760, 1740, 168, 61, 1.12, 700]],
      ['MOV_N_W_SLIP', 'Right (slip lane)', [8, SLIP, SLIP, SLIP, SLIP, 18, 5, 0.3, 90]],
    ]),
  ]
}

// The intersection on its own, for pages that only need its name and position
export async function getIntersection() {
  await wait(150)
  return INTERSECTION
}

// Gives back everything the Current Traffic page shows. It is "async" because the real version
// will wait for the server; the sample version waits a moment to behave the same way.
export async function getCurrentTraffic() {
  await wait(300)

  // FOR TESTING ONLY: add ?demo=empty or ?demo=error to the page address
  // to see the empty and error states.
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'error') throw new Error('The traffic service is not responding.')
  if (demo === 'empty') {
    return {
      isSample: true,
      intersection: INTERSECTION,
      timeline: [],
      kpis: [],
      alerts: [],
      approaches: [],
    }
  }

  const interval = latestInterval()
  const previousInterval = latestInterval(Date.parse(interval[0]))

  return {
    isSample: true,
    intersection: INTERSECTION,
    timeline: sampleTimelineBars(),
    kpis: sampleIntersectionKpis(interval, previousInterval),
    alerts: SAMPLE_ALERTS,
    approaches: sampleApproaches(interval),
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
