// Data for the Current Traffic page. The intersection comes from our SUMO setup. The timeline,
// KPIs and alerts are sample values until the backend API is ready, then only this file changes.

const CENTER = [46.633621, 24.735289]

// Half the width of the square that is shown around the centre, in metres. 350 m is just inside
// the shortest main road in the network (Turki Rd going north-west ends at about 359 m), so every
// main road reaches the edge and they are all cut at the same line.
const HALF_SIZE_M = 350
const M_PER_DEG_LAT = 110540
const M_PER_DEG_LON = 111320 * Math.cos((CENTER[1] * Math.PI) / 180)

// id is the folder in public/data, center is where the 3D camera starts
export const INTERSECTION = {
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

// changeTone decides the colour: green for good, red for bad
export const SAMPLE_KPIS = [
  { label: 'Control Delay', value: 46, unit: 's', change: 4, changeTone: 'bad' },
  { label: 'Queue Length', value: 128, unit: 'm', change: 12, changeTone: 'bad' },
  { label: 'Avg Speed', value: 24, unit: 'km/h', change: -6, changeTone: 'bad' },
  { label: 'Throughput', value: 1842, unit: 'veh/h', change: 3, changeTone: 'good' },
  { label: 'V/C Ratio', value: 0.91, change: 0.04, changeUnit: '', changeTone: 'bad' },
  { label: 'Level of Service' }, // no value yet, shows "Unavailable"
]

// Click an alert to see where and when it was detected, like the Forecast Alerts
export const SAMPLE_ALERTS = [
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
// only. The right turns leave before the signal on slip lanes, so the signal measures (LOS,
// v/c, capacity, saturation flow) don't apply to them and are 'na'.
// A value of null means unavailable, 'na' means not applicable.
// arm is the side of the junction the approach comes from (matches the 3D scene).
const NA = 'na'
const kpis = (delay, vc, capacity, satFlow, queue, queueDuration, storage, throughput) => ({
  delay,
  los: delay === NA ? NA : losFromDelay(delay, vc),
  vc,
  capacity,
  satFlow,
  queue,
  queueDuration,
  storage,
  throughput,
})

export const SAMPLE_APPROACHES = [
  {
    id: 'E',
    arm: 'East',
    road: 'Imam Saud Rd',
    kpis: kpis(52, 0.94, 1710, null, 142, 38, 0.81, 1650),
    movements: [
      { id: 'E-T', type: 'Through', kpis: kpis(44, 0.88, 1180, 1820, 118, 31, 0.67, 1040) },
      { id: 'E-L', type: 'Left', kpis: kpis(71, 0.94, 530, 1760, 142, 52, 0.81, 500) },
      { id: 'E-R', type: 'Right (slip lane)', kpis: kpis(9, NA, NA, NA, 21, 6, 0.35, 110) },
    ],
  },
  {
    id: 'W',
    arm: 'West',
    road: 'Imam Saud Rd',
    kpis: kpis(41, 0.83, 1420, null, 109, 29, 0.66, 1290),
    movements: [
      { id: 'W-T', type: 'Through', kpis: kpis(36, 0.79, 960, 1800, 96, 26, 0.58, 760) },
      { id: 'W-L', type: 'Left', kpis: kpis(53, 0.83, 460, 1750, 109, 35, 0.66, 380) },
      { id: 'W-R', type: 'Right (slip lane)', kpis: kpis(7, NA, NA, NA, 15, 4, 0.25, 150) },
    ],
  },
  {
    id: 'S',
    arm: 'South',
    road: 'Prince Turki Rd, service road',
    kpis: kpis(33, 0.71, 1020, null, 74, 22, 0.52, 720),
    movements: [
      { id: 'S-T', type: 'Through', kpis: kpis(33, 0.71, 1020, 1790, 74, 22, 0.52, 640) },
      { id: 'S-R', type: 'Right (slip lane)', kpis: kpis(6, NA, NA, NA, 12, 3, 0.2, 80) },
    ],
  },
  {
    id: 'N',
    arm: 'North',
    road: 'Prince Turki Rd, service road',
    kpis: kpis(58, 1.04, 760, null, 168, 61, 1.12, 790),
    movements: [
      { id: 'N-L', type: 'Left', kpis: kpis(64, 1.04, 760, 1740, 168, 61, 1.12, 700) },
      { id: 'N-R', type: 'Right (slip lane)', kpis: kpis(8, NA, NA, NA, 18, 5, 0.3, 90) },
    ],
  },
]

// HCM signalized intersection LOS from control delay (s/veh); v/c above 1 is always F
function losFromDelay(delay, vc) {
  if (delay === null) return null
  if (typeof vc === 'number' && vc > 1) return 'F'
  if (delay <= 10) return 'A'
  if (delay <= 20) return 'B'
  if (delay <= 35) return 'C'
  if (delay <= 55) return 'D'
  if (delay <= 80) return 'E'
  return 'F'
}
