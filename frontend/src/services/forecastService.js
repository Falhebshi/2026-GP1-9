// Where the Traffic Forecast page gets its data.
//
// For now it returns SAMPLE data. When the forecast run and its API are ready, only the inside
// of getForecast() changes; the page stays the same as long as the data keeps this shape:
//
//   {
//     isSample: true,                    true while the data is sample data
//     intersection: { id, center, bounds, name, area, approaches, signalType },
//     kpis: { 15: [...], 30: [...], 45: [...], 60: [...] },   predicted intersection KPIs
//                                        per horizon, each [{ current: KpiResult, previous: KpiResult }]
//                                        where previous is the value now, for the change
//     approaches: { 15: [...], 30: [...], 45: [...], 60: [...] },   predicted approach KPIs per
//                                        horizon, the same shape as on Current Traffic
//     alerts: [{ id, title, details: [{ label, value }] }],
//   }

import { getIntersection, sampleApproaches } from './currentTrafficService'
import { latestInterval, sampleResult, unavailableResult } from './sampleKpiResults'

const ELEMENT = { level: 'intersection', id: 'INT_001' }
const HORIZONS = [15, 30, 45, 60]

// The intersection now, the same numbers as the Current Traffic sample
const NOW = {
  control_delay: 46,
  queue_length: 128,
  queue_duration: 37,
  queue_storage_ratio: 1.12,
  throughput: 1842,
  volume_to_capacity_ratio: 0.91,
}

// Predicted values at each horizon (minutes ahead)
const PREDICTED = {
  15: {
    control_delay: 50,
    queue_length: 138,
    queue_duration: 40,
    queue_storage_ratio: 1.15,
    throughput: 1780,
    volume_to_capacity_ratio: 0.84,
  },
  30: {
    control_delay: 55,
    queue_length: 150,
    queue_duration: 44,
    queue_storage_ratio: 1.2,
    throughput: 1701,
    volume_to_capacity_ratio: 0.81,
  },
  45: {
    control_delay: 58,
    queue_length: 162,
    queue_duration: 47,
    queue_storage_ratio: 1.24,
    throughput: 1655,
    volume_to_capacity_ratio: 0.88,
  },
  60: {
    control_delay: 52,
    queue_length: 144,
    queue_duration: 42,
    queue_storage_ratio: 1.18,
    throughput: 1724,
    volume_to_capacity_ratio: 0.83,
  },
}

// The 15 minutes that end `minutes` after the latest interval
function intervalAhead(now, minutes) {
  const end = Date.parse(now[1]) + minutes * 60 * 1000
  return [new Date(end - 15 * 60 * 1000).toISOString(), new Date(end).toISOString()]
}

function sampleForecastKpis() {
  const now = latestInterval()
  const kpis = {}
  for (const horizon of HORIZONS) {
    const interval = intervalAhead(now, horizon)
    kpis[horizon] = Object.entries(PREDICTED[horizon]).map(([kpi, value]) => ({
      current: sampleResult(kpi, value, ELEMENT, interval),
      previous: sampleResult(kpi, NOW[kpi], ELEMENT, now),
    }))
    // LOS is left out of the forecast sample on purpose, to show how a missing value looks
    kpis[horizon].push({
      current: unavailableResult(
        'level_of_service',
        ELEMENT,
        interval,
        'Not calculated for forecasts yet.',
      ),
      previous: null,
    })
  }
  return kpis
}

// Predicted approach KPIs per horizon. For now the same sample values as Current Traffic, for
// the interval of each horizon.
function sampleForecastApproaches() {
  const now = latestInterval()
  return Object.fromEntries(
    HORIZONS.map((horizon) => [horizon, sampleApproaches(intervalAhead(now, horizon))]),
  )
}

// Problems the forecast expects. Click one to see where and when.
const SAMPLE_FORECAST_ALERTS = [
  {
    id: 'f1',
    title: 'Queue spillback',
    details: [
      { label: 'Location', value: 'North approach' },
      { label: 'When', value: 'After 15 min' },
    ],
  },
  {
    id: 'f2',
    title: 'Low average speed',
    details: [
      { label: 'Location', value: 'East approach' },
      { label: 'When', value: 'After 30 min' },
    ],
  },
  {
    id: 'f3',
    title: 'High V/C ratio',
    details: [
      { label: 'Location', value: 'West approach' },
      { label: 'When', value: 'After 45 min' },
    ],
  },
]

// Gives back the forecast. "async" because the real version will wait for the server.
export async function getForecast() {
  const intersection = await getIntersection()

  // FOR TESTING ONLY: ?demo=empty or ?demo=error in the page address
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'error') throw new Error('The forecast service is not responding.')
  if (demo === 'empty') {
    const none = { 15: [], 30: [], 45: [], 60: [] }
    return { isSample: true, intersection, kpis: none, approaches: none, alerts: [] }
  }

  return {
    isSample: true,
    intersection,
    kpis: sampleForecastKpis(),
    approaches: sampleForecastApproaches(),
    alerts: SAMPLE_FORECAST_ALERTS,
  }
}
