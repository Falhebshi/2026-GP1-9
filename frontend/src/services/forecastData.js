// Sample data for the Traffic Forecast page until the forecast run and its API are ready.
// When they are, replace these two exports with the real data in the same shape.

// Predicted KPIs at each forecast horizon (minutes ahead), in the same shape KpiTile takes.
// change is compared with now; changeTone says whether that change is good or bad.
export const SAMPLE_FORECAST_KPIS = {
  15: [
    { label: 'Control Delay', value: 50, unit: 's', change: 2, changeTone: 'bad' },
    { label: 'Queue Length', value: 138, unit: 'm', change: 6, changeTone: 'bad' },
    { label: 'Avg Speed', value: 22, unit: 'km/h', change: -3, changeTone: 'bad' },
    { label: 'Throughput', value: 1780, unit: 'veh/h', change: 2, changeTone: 'good' },
    { label: 'V/C Ratio', value: 0.84, change: 0.02, changeUnit: '', changeTone: 'bad' },
    { label: 'Level of Service' },
  ],
  30: [
    { label: 'Control Delay', value: 55, unit: 's', change: 4, changeTone: 'bad' },
    { label: 'Queue Length', value: 150, unit: 'm', change: 12, changeTone: 'bad' },
    { label: 'Avg Speed', value: 19, unit: 'km/h', change: -6, changeTone: 'bad' },
    { label: 'Throughput', value: 1701, unit: 'veh/h', change: 3, changeTone: 'good' },
    { label: 'V/C Ratio', value: 0.81, change: 0.04, changeUnit: '', changeTone: 'bad' },
    { label: 'Level of Service' },
  ],
  45: [
    { label: 'Control Delay', value: 58, unit: 's', change: 7, changeTone: 'bad' },
    { label: 'Queue Length', value: 162, unit: 'm', change: 15, changeTone: 'bad' },
    { label: 'Avg Speed', value: 18, unit: 'km/h', change: -9, changeTone: 'bad' },
    { label: 'Throughput', value: 1655, unit: 'veh/h', change: -1, changeTone: 'bad' },
    { label: 'V/C Ratio', value: 0.88, change: 0.06, changeUnit: '', changeTone: 'bad' },
    { label: 'Level of Service' },
  ],
  60: [
    { label: 'Control Delay', value: 52, unit: 's', change: 3, changeTone: 'bad' },
    { label: 'Queue Length', value: 144, unit: 'm', change: 9, changeTone: 'bad' },
    { label: 'Avg Speed', value: 21, unit: 'km/h', change: -4, changeTone: 'bad' },
    { label: 'Throughput', value: 1724, unit: 'veh/h', change: 1, changeTone: 'good' },
    { label: 'V/C Ratio', value: 0.83, change: 0.03, changeUnit: '', changeTone: 'bad' },
    { label: 'Level of Service' },
  ],
}

// Problems the forecast expects. Click one to see where and when.
export const SAMPLE_FORECAST_ALERTS = [
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
