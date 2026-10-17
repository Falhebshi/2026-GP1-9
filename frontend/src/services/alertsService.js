// Where the Alerts page gets its data.
//
// For now it returns FAKE data. When the backend is ready, only the inside
// of getAlerts() changes (it will fetch from the server); the page that
// calls it stays the same, as long as the data keeps this shape:
//
//   {
//     area: 'Intersection A',            name of the selected area
//     current: [                         abnormal conditions right now
//       { id, title, area, detectedAt: '14:05', status: 'active',
//         interventionId }               interventionId: null when none
//     ],
//     forecast: [                        problems expected soon
//       { id, title, area, expectedInMinutes: 25, horizonMinutes: 30,
//         interventionId }
//     ],
//     pattern: [                         problems that repeat
//       { id, title, location, when: 'Weekdays, 07:30-09:00',
//         daysSeen: 4, daysTotal: 5, interventionId }
//     ],
//   }
//
// Resolved alerts are not included: the backend only sends active ones.

const FAKE_ALERTS = {
  area: 'Intersection A',
  current: [
    { id: 'c1', title: 'Queue spillback', area: 'North approach', detectedAt: '14:05', status: 'active', interventionId: 1 },
    { id: 'c2', title: 'Low average speed', area: 'East approach', detectedAt: '13:48', status: 'active', interventionId: 2 },
    { id: 'c3', title: 'High V/C ratio', area: 'West approach', detectedAt: '13:20', status: 'active', interventionId: null },
    { id: 'c4', title: 'Signal timing issue', area: 'South approach', detectedAt: '12:55', status: 'active', interventionId: 6 },
    { id: 'c5', title: 'Lane blockage', area: 'North approach', detectedAt: '12:31', status: 'active', interventionId: null },
  ],
  forecast: [
    { id: 'f1', title: 'High V/C ratio', area: 'West approach', expectedInMinutes: 25, horizonMinutes: 30, interventionId: 3 },
    { id: 'f2', title: 'Queue buildup', area: 'South approach', expectedInMinutes: 12, horizonMinutes: 15, interventionId: 4 },
    { id: 'f3', title: 'Low average speed', area: 'North approach', expectedInMinutes: 40, horizonMinutes: 60, interventionId: null },
  ],
  pattern: [
    { id: 'p1', title: 'Recurring queue buildup', location: 'North approach', when: 'Weekdays, 07:30-09:00', daysSeen: 4, daysTotal: 5, interventionId: 1 },
    { id: 'p2', title: 'Recurring low speed', location: 'East approach', when: 'Weekdays, 16:00-18:00', daysSeen: 3, daysTotal: 5, interventionId: 5 },
    { id: 'p3', title: 'Recurring high V/C', location: 'West approach', when: 'Weekends, 12:00-15:00', daysSeen: 2, daysTotal: 2, interventionId: null },
  ],
}

// Gives back the alerts. It is "async" because the real version will wait
// for the server; the fake version waits a moment to behave the same way.
export async function getAlerts() {
  await wait(300)

  // FOR TESTING ONLY: add ?demo=empty or ?demo=error to the page address
  // to see the empty and error states.
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'error') throw new Error('The alert service is not responding.')
  if (demo === 'empty') return { area: FAKE_ALERTS.area, current: [], forecast: [], pattern: [] }

  return FAKE_ALERTS
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}