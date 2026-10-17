// Where the Traffic Forecast page gets its data.
//
// For now it returns SAMPLE data. When the forecast run and its API are ready, only the inside
// of getForecast() changes; the page stays the same as long as the data keeps this shape:
//
//   {
//     isSample: true,                    true while the data is sample data
//     intersection: { id, center, bounds, name, area, approaches, signalType },
//     kpis: { 15: [...], 30: [...], 45: [...], 60: [...] },   predicted KPIs per horizon,
//                                        each [{ label, value, unit, change, changeTone }]
//     alerts: [{ id, title, details: [{ label, value }] }],
//   }

import { getIntersection } from './currentTrafficService'

// Predicted KPIs at each forecast horizon (minutes ahead), in the same shape KpiTile takes.
// change is compared with now; changeTone says whether that change is good or bad.
const SAMPLE_FORECAST_KPIS = {
  15: [
    { label: 'Control Delay', value: 50, unit: 's/veh', change: 2, changeTone: 'bad' },
    { label: 'Queue Length', value: 138, unit: 'm', change: 6, changeTone: 'bad' },
    { label: 'Throughput', value: 1780, unit: 'veh/h', change: 2, changeTone: 'good' },
    { label: 'V/C Ratio', value: 0.84, change: 0.02, changeUnit: '', changeTone: 'bad' },
    { label: 'Level of Service' },
  ],
  30: [
    { label: 'Control Delay', value: 55, unit: 's/veh', change: 4, changeTone: 'bad' },
    { label: 'Queue Length', value: 150, unit: 'm', change: 12, changeTone: 'bad' },
    { label: 'Throughput', value: 1701, unit: 'veh/h', change: 3, changeTone: 'good' },
    { label: 'V/C Ratio', value: 0.81, change: 0.04, changeUnit: '', changeTone: 'bad' },
    { label: 'Level of Service' },
  ],
  45: [
    { label: 'Control Delay', value: 58, unit: 's/veh', change: 7, changeTone: 'bad' },
    { label: 'Queue Length', value: 162, unit: 'm', change: 15, changeTone: 'bad' },
    { label: 'Throughput', value: 1655, unit: 'veh/h', change: -1, changeTone: 'bad' },
    { label: 'V/C Ratio', value: 0.88, change: 0.06, changeUnit: '', changeTone: 'bad' },
    { label: 'Level of Service' },
  ],
  60: [
    { label: 'Control Delay', value: 52, unit: 's/veh', change: 3, changeTone: 'bad' },
    { label: 'Queue Length', value: 144, unit: 'm', change: 9, changeTone: 'bad' },
    { label: 'Throughput', value: 1724, unit: 'veh/h', change: 1, changeTone: 'good' },
    { label: 'V/C Ratio', value: 0.83, change: 0.03, changeUnit: '', changeTone: 'bad' },
    { label: 'Level of Service' },
  ],
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
    return { isSample: true, intersection, kpis: { 15: [], 30: [], 45: [], 60: [] }, alerts: [] }
  }

  return {
    isSample: true,
    intersection,
    kpis: SAMPLE_FORECAST_KPIS,
    alerts: SAMPLE_FORECAST_ALERTS,
  }
}
