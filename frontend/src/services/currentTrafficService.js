// Where the Current Traffic page gets its data.
//
// For now it returns SAMPLE data. When the backend is ready, only the inside of
// getCurrentTraffic() changes; the page stays the same as long as the data keeps this shape:
//
//   {
//     isSample: true,                    true while the data is sample data
//     intersection: { id, center, bounds, name, area, approaches, signalType },
//     timeline: [{ time, value, level }],      one bar per 15 minutes, last 24 hours
//     kpis: [{ label, value, unit, change, changeUnit, changeTone }],
//     alerts: [{ id, title, details: [{ label, value }], interventionsTo }],
//     approaches: [{ id, arm, road, kpis, movements: [{ id, type, kpis }] }],
//   }
//
// The KPI values (including the LOS grade) come from the backend; this file never calculates
// them. The KPIs follow the team's KPI list (Capacity Engine Handoff, section 3).

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

// changeTone decides the color: green for good, red for bad
const SAMPLE_KPIS = [
  { label: 'Control Delay', value: 46, unit: 's/veh', change: 4, changeTone: 'bad' },
  { label: 'Queue Length', value: 128, unit: 'm', change: 12, changeTone: 'bad' },
  { label: 'Throughput', value: 1842, unit: 'veh/h', change: 3, changeTone: 'good' },
  { label: 'V/C Ratio', value: 0.91, change: 0.04, changeUnit: '', changeTone: 'bad' },
  { label: 'Level of Service' }, // no value yet, shows "Unavailable"
]

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
// don't apply to them and are 'na'. Whether slip lanes get KPIs at all is still open.
// A value of null means unavailable, 'na' means not applicable.
// arm is the side of the junction the approach comes from (matches the 3D scene).
const NA = 'na'
const kpis = (delay, los, vc, capacity, satFlow, queue, queueDuration, storage, throughput) => ({
  delay,
  los,
  vc,
  capacity,
  satFlow,
  queue,
  queueDuration,
  storage,
  throughput,
})

const SAMPLE_APPROACHES = [
  {
    id: 'E',
    arm: 'East',
    road: 'Imam Saud Rd',
    kpis: kpis(52, 'D', 0.94, 1710, null, 142, 38, 0.81, 1540),
    movements: [
      { id: 'E-T', type: 'Through', kpis: kpis(44, 'D', 0.88, 1180, 1820, 118, 31, 0.67, 1040) },
      { id: 'E-L', type: 'Left', kpis: kpis(71, 'E', 0.94, 530, 1760, 142, 52, 0.81, 500) },
    ],
  },
  {
    id: 'W',
    arm: 'West',
    road: 'Imam Saud Rd',
    kpis: kpis(41, 'D', 0.83, 1420, null, 109, 29, 0.66, 1290),
    movements: [
      { id: 'W-T', type: 'Through', kpis: kpis(36, 'D', 0.79, 960, 1800, 96, 26, 0.58, 760) },
      { id: 'W-L', type: 'Left', kpis: kpis(53, 'D', 0.83, 460, 1750, 109, 35, 0.66, 380) },
      { id: 'W-R', type: 'Right (slip lane)', kpis: kpis(7, NA, NA, NA, NA, 15, 4, 0.25, 150) },
    ],
  },
  {
    id: 'S',
    arm: 'South',
    road: 'Prince Turki Rd, service road',
    kpis: kpis(33, 'C', 0.71, 1020, null, 74, 22, 0.52, 720),
    movements: [
      { id: 'S-T', type: 'Through', kpis: kpis(33, 'C', 0.71, 1020, 1790, 74, 22, 0.52, 640) },
      { id: 'S-R', type: 'Right (slip lane)', kpis: kpis(6, NA, NA, NA, NA, 12, 3, 0.2, 80) },
    ],
  },
  {
    id: 'N',
    arm: 'North',
    road: 'Prince Turki Rd, service road',
    kpis: kpis(58, 'F', 1.04, 760, null, 168, 61, 1.12, 790),
    movements: [
      { id: 'N-L', type: 'Left', kpis: kpis(64, 'F', 1.04, 760, 1740, 168, 61, 1.12, 700) },
      { id: 'N-R', type: 'Right (slip lane)', kpis: kpis(8, NA, NA, NA, NA, 18, 5, 0.3, 90) },
    ],
  },
]

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

  return {
    isSample: true,
    intersection: INTERSECTION,
    timeline: sampleTimelineBars(),
    kpis: SAMPLE_KPIS,
    alerts: SAMPLE_ALERTS,
    approaches: SAMPLE_APPROACHES,
  }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
