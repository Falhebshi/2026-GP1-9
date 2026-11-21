// Where the Current Traffic page gets its data.
//
// The page shows the live run in public/data/<intersection>/live/ when the live update loop
// (simulation/scripts/run_live.py) has published one, and otherwise the committed sample run in
// baseline/, labelled as a sample. Never both: the folder is picked by its run.json (team
// decision A on live outputs). From the folder it reads the run (run.json) and its KPI results
// (kpis.json, KpiResult records from the KPI engine), and the approaches from
// network/approaches.json. The alerts are still sample data. getCurrentTraffic() gives back:
//
//   {
//     source: 'run',                     'live' for the live run, 'run' for the sample run
//     scenario: 'baseline',              the folder the run is in: 'live' or 'baseline'
//     isSample: true when the page shows the committed sample run, because nothing is live
//     live: null for the sample run; for the live run:
//       { state, message,                'running', 'starting' (a new run is warming up and the
//                                        previous one is shown), 'waiting' (the source cannot
//                                        be reached), 'paused' or 'stopped', and why
//         updatedAt, dataUntil,          when the loop last reported (real time) and the end of
//                                        the newest interval it has simulated (data time), ISO
//         stale,                         true when the loop has not reported for 30 minutes
//         clockOffsetMs,                 how far the source's clock is behind the real clock
//                                        (13 weeks for the replay source, 0 on real time)
//         simulatedUntilSeconds,         where the simulation stopped, in seconds from the run
//                                        start (the warm-up)
//         version }                      changes whenever a new interval is published
//     previous: null, or for a live run the run before it, while it is less than 24 hours old
//       (live/previous/): { scenario: 'live/previous', run, hasKpis, isTest, intervals,
//       timeline } as below, with only the intervals before the newest run's first one
//     intersection: { id, center, bounds, name, area, approaches, signalType },
//     run: { id, status, failureReason, start, duration, intervalSeconds, analysisStartSeconds },
//                                        null when there is no run yet. status 'completed',
//                                        'running' (a live run) or 'failed' (then failureReason
//                                        says why, and there are no intervals). start: the start
//                                        of the analysis period (ISO time); duration and
//                                        intervalSeconds in seconds
//     hasKpis: false when the run has no KPI results yet (no kpis.json, or one of another run)
//     isTest: true when the run or its KPIs are test data ("is_test" in run.json or kpis.json)
//     intervals: [{                      one per 15 minutes of the analysis period, oldest first
//       start, end,                      ISO times
//       provisional,                     true for the newest interval of a live run: simulated up to
//                                        60 s before its end, with some vehicles still driving, so
//                                        its values change at the next update
//       noSensorData,                    null, or { approachIds } when the detectors were silent and
//                                        the traffic was estimated: its KPIs are left out (kpis is
//                                        empty, approach and movement kpis are {}), and the page
//                                        shows "No detector data" instead (team decision, option 3)
//       kpis: [{ current: KpiResult, previous: KpiResult }],   intersection level; previous is
//                                        the interval before in the same run (null for the first)
//       approaches: [{
//         approach_id, arm, road,
//         kpis: { <kpi name>: KpiResult },                    approach level
//         movements: [{ movement_id, label, kpis: { <kpi name>: KpiResult } }],
//       }],
//     }],
//     timeline: [{ time, value, level }],      one bar per interval, from the intersection's delay;
//                                        no bar (no value) for an interval without detector data
//     alerts: [{ id, title, details: [{ label, value }], detailsTo }],
//   }
//
// Every KPI value is a KpiResult, exactly as the backend's KPI engine sends it (data_models.md,
// section 6). Pages show them with src/utils/kpi.js. This file never calculates a KPI.

import { notApplicableResult, sampleResult } from './sampleKpiResults'
import { roadName } from '../utils/roadName'

// The study intersection. Its name, area and centre come from its record in
// public/data/intersections.json, a copy of data/processed/intersections.json.
const INTERSECTION_ID = 'INT_001'

// Half the width of the square that is shown around the centre, in metres. 350 m is just inside
// the shortest main road in the network (Turki Road going north-west ends at about 359 m), so every
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
    approach('APP_E', 'East', 'Imam Saud Road', [52, 'D', 0.94, 1710, M, 142, 38, 0.81, 1540], [
      ['MOV_E_W', 'Through', [44, 'D', 0.88, 1180, 1820, 142, 31, 0.81, 1040], 'LANE_E_2'],
      ['MOV_E_S', 'Left', [71, 'E', 0.94, 530, 1760, 142, 52, 0.81, 500], 'LANE_E_2'],
    ]),
    approach('APP_W', 'West', 'Imam Saud Road', [41, 'D', 0.83, 1420, M, 109, 29, 0.66, 1290], [
      ['MOV_W_E', 'Through', [36, 'D', 0.79, 960, 1800, 109, 26, 0.66, 760], 'LANE_W_2'],
      ['MOV_W_N', 'Left', [53, 'D', 0.83, 460, 1750, 109, 35, 0.66, 380], 'LANE_W_2'],
      ['MOV_W_S_SLIP', 'Right (slip lane)', [7, SLIP, SLIP, SLIP, SLIP, 15, 4, 0.25, 150]],
    ]),
    approach('APP_S', 'South', 'Prince Turki Road, service road', [33, 'C', 0.71, 1020, M, 74, 22, 0.52, 720], [
      ['MOV_S_W', 'Left', [33, 'C', 0.71, 1020, 1790, 74, 22, 0.52, 640]],
      ['MOV_S_E_BYPASS', 'Right (slip lane)', [6, SLIP, SLIP, SLIP, SLIP, 12, 3, 0.2, 80]],
    ]),
    approach('APP_N', 'North', 'Prince Turki Road, service road', [58, 'F', 1.04, 760, M, 168, 61, 1.12, 790], [
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
    name: roadName(record.name_en),
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

  // The live run if there is one (?demo=sample shows the sample run anyway)
  const liveRun =
    demo === 'no-run' || demo === 'sample' ? null : await getJson(`${folder}/live/run.json`)
  const scenario = liveRun ? 'live' : 'baseline'
  let run = liveRun ?? (demo === 'no-run' ? null : await getJson(`${folder}/baseline/run.json`))
  if (run && demo === 'failed') {
    run = { ...run, status: 'failed', failure_reason: 'TraCIException: connection closed by SUMO' }
  }
  const page = {
    source: liveRun ? 'live' : 'run',
    scenario,
    isSample: !liveRun && Boolean(run),
    live: liveRun ? liveState(liveRun) : null,
    intersection,
    alerts: SAMPLE_ALERTS,
  }

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
      isTest: Boolean(run?.is_test),
      intervals: [],
      timeline: [],
      previous: null,
    }
  }

  const status = liveRun ? 'running' : 'completed'
  const current = await runView(folder, scenario, run, approaches, demo, status)

  // Live only: the run before this one (the day before, or the chain before a restart), kept
  // in live/previous/ until its intervals are 24 hours old, so the timeline shows the last
  // 24 hours. Its intervals start where they end in the newest run, never overlapping it.
  let previous = null
  const previousRun =
    liveRun && demo !== 'empty' ? await getJson(`${folder}/live/previous/run.json`) : null
  if (previousRun && previousRun.run_id !== run.run_id && previousRun.status !== 'failed') {
    const view = await runView(folder, 'live/previous', previousRun, approaches, demo, 'completed')
    const firstStart = current.intervals[0] ? Date.parse(current.intervals[0].start) : Infinity
    const intervals = view.intervals.filter((item) => Date.parse(item.start) < firstStart)
    if (intervals.length) {
      previous = {
        ...view,
        scenario: 'live/previous',
        intervals,
        timeline: intervals.map(timelineBar),
      }
    }
  }

  return { ...page, ...current, previous }
}

// One run as the page shows it: the run, its intervals with their KPIs and the timeline bars
async function runView(folder, scenario, run, approaches, demo, status) {
  // Only the KPI results of this run; a kpis.json left from another run is not used
  const kpis = demo === 'no-kpis' ? null : await getJson(`${folder}/${scenario}/kpis.json`)
  const results = kpis?.run_id === run.run_id ? kpis.results : null
  const intervals =
    demo === 'empty' ? [] : groupByInterval(run, results ?? [], approaches.approaches)

  return {
    run: {
      id: run.run_id,
      status,
      failureReason: null,
      start: addSeconds(run.run_start, run.analysis_start_s),
      duration: run.analysis_end_s - run.analysis_start_s,
      intervalSeconds: run.interval_s,
      // seconds from the run start (the warm-up) to the analysis period: the scene's own clock
      analysisStartSeconds: run.analysis_start_s,
    },
    hasKpis: results !== null,
    isTest: Boolean(run.is_test || (results && kpis.is_test)),
    intervals,
    timeline: intervals.map(timelineBar),
  }
}

// A live run stops counting as live when the loop has not reported for this long: it reports
// every 10 seconds, and publishes a new interval every 15 minutes
const STALE_AFTER = 30 * 60 * 1000

// What the page shows about the live loop, from run.json's "live" part
function liveState(run) {
  const live = run.live ?? {}
  return {
    state: live.state ?? 'running',
    message: live.message ?? null,
    updatedAt: live.updated_at ?? null,
    dataUntil: live.data_until ?? null,
    stale: live.updated_at ? Date.now() - Date.parse(live.updated_at) > STALE_AFTER : false,
    clockOffsetMs: (live.clock_offset_s ?? 0) * 1000,
    simulatedUntilSeconds: live.simulated_until_s ?? null,
    version: `${run.run_id}|${live.data_until ?? ''}`,
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
  // Live runs only: the intervals with estimated traffic, and the provisional (newest) one
  const estimated = (run.live?.estimated_intervals ?? []).map((item) => ({
    start: addSeconds(run.run_start, item.start_s),
    approachIds: item.approach_ids,
  }))
  const provisional =
    run.live?.provisional_interval_start_s != null
      ? addSeconds(run.run_start, run.live.provisional_interval_start_s)
      : null

  return starts.map((start, i) => {
    const before = starts[i - 1]
    const noSensorData = estimated.find((item) => at(item.start) === at(start)) ?? null
    const end = addSeconds(start, run.interval_s)

    // No detector data: the results come from estimated traffic, so none are shown
    if (noSensorData) {
      return {
        start,
        end,
        provisional: false,
        noSensorData: { approachIds: noSensorData.approachIds },
        kpis: [],
        approaches: approaches.map((a) => ({
          approach_id: a.approach_id,
          arm: a.side[0].toUpperCase() + a.side.slice(1),
          road: a.road,
          kpis: {},
          movements: a.movements.map((m) => ({
            movement_id: m.movement_id,
            label: movementLabel(m),
            kpis: {},
          })),
        })),
      }
    }

    const intersection = Object.values(of('intersection', run.intersection_id, start))

    return {
      start,
      end,
      provisional: provisional !== null && at(provisional) === at(start),
      noSensorData: null,
      kpis: intersection.map((current) => ({
        current,
        // no comparison with an interval whose values are not shown
        previous:
          before && !estimated.some((item) => at(item.start) === at(before))
            ? (of('intersection', run.intersection_id, before)[current.kpi] ?? null)
            : null,
      })),
      approaches: approaches.map((a) => ({
        approach_id: a.approach_id,
        arm: a.side[0].toUpperCase() + a.side.slice(1),
        road: roadName(a.road),
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
// where LOS F starts, is a full bar) and its colour from the level of service. No delay, no bar,
// and the note says why: no detector data, or the delay could not be measured (an approach's
// queue reaching past its measurement zone says so on the approach, not on the intersection).
function timelineBar({ start, kpis, approaches, noSensorData }) {
  const result = (kpi) => kpis.find((k) => k.current.kpi === kpi)?.current
  const delay = result('control_delay')
  const grade = result('level_of_service')?.los_grade

  return {
    time: start,
    value: delay?.status === 'ok' ? Math.min(1, delay.value / 80) : undefined,
    level: BAR_LEVELS[grade],
    note: barNote(delay, approaches, noSensorData),
  }
}

// An approach's KPIs are keyed by KPI name (see `of` in runView)
const approachDelay = (approach) => approach.kpis?.control_delay

// Why a bar has no value, in words for the timeline
function barNote(delay, approaches, noSensorData) {
  if (noSensorData) return 'No detector data'
  if (!delay || delay.status === 'ok') return undefined
  // the approaches whose queue reached past their measurement zone (the KPI engine's
  // ZONE_END_REASON; tests/test_kpi_reasons.py fails if its wording loses these words)
  const beyond = (approaches ?? [])
    .filter((a) => approachDelay(a)?.reason?.includes(ZONE_END_WORDS))
    .map((a) => a.arm)
  if (beyond.length) {
    return `Delay not measured: ${beyond.join(' and ')} queue beyond the measured area`
  }
  if (delay.reason?.includes(ZONE_END_WORDS)) {
    return 'Delay not measured: queue beyond the measured area'
  }
  return 'Delay not measured'
}

const ZONE_END_WORDS = 'end of the measurement zone'
