// Where the Network Traffic Overview page gets its data.
//
// For now it returns SAMPLE data. When the backend is ready, only the inside of these functions
// changes; the page stays the same as long as the data keeps these shapes:
//
//   getNetwork()           { isSample, bounds: [[west, south], [east, north]],
//                            intersections: [{ id, name, area, center, simulation }] }
//   getNetworkTimeline(t)  { isSample, bars: [{ time, value, level }] }, 24 hours ending at t
//   getSegments(time)      GeoJSON road segments, or null while not connected (see below)

import { getIntersection, sampleTimelineBars } from './currentTrafficService'

// Road segment congestion is NOT connected yet: the source (RCRC, TomTom or another feed) is
// decided next sprint, so getSegments returns null for now and the map shows the plain basemap.
// When the source is ready, only getSegments has to change. It should resolve to a GeoJSON
// FeatureCollection of LineStrings, one per road segment, with these properties:
//   id          unique id of the segment
//   name        road name, e.g. 'King Fahd Rd'
//   congestion  0 (free flow) to 1 (standstill); sets the heatmap weight
//   level       'low', 'moderate' or 'high'; sets the line color
//   speed       average speed in km/h (optional, shown on hover)
// It will take the moment to show (an ISO time string, or null for the latest data).
export async function getSegments() {
  return null
}

// The area the map shows: north Riyadh around King Fahd Rd and the Northern Ring Rd.
const NETWORK_BOUNDS = [
  [46.585, 24.69],
  [46.73, 24.8],
]

// The other intersections in the "Intersections by area" list. Positions are where the two roads
// cross in OpenStreetMap. Districts checked on Google Maps (25 and 28 Oct). King Abdullah × King
// Fahd sits where four districts meet (Ar Rahmaniyyah, Al Mohammadiyyah, Al Wurud and King Fahd);
// it is listed under Ar Rahmaniyyah, the first one Google Maps gives. They are listed but not
// active yet: only the study intersection, which comes from its record (getIntersection), has a
// simulation.
const OTHER_INTERSECTIONS = [
  {
    id: 'imamsaud_takhassusi',
    name: 'Imam Saud Rd × Takhassusi Rd',
    area: 'Al Nakheel',
    center: [46.64549, 24.74039],
  },
  {
    id: 'kingabdullah_kingfahd',
    name: 'King Abdullah Rd × King Fahd Rd',
    area: 'Ar Rahmaniyyah',
    center: [46.66386, 24.7276],
  },
  {
    id: 'turki_urubah',
    name: 'Prince Turki Al-Awwal Rd × Al Urubah Rd',
    area: 'Umm Al Hamam Al Gharbi',
    center: [46.65406, 24.70431],
  },
]

// The map area and the intersections in the "Intersections by area" list
export async function getNetwork() {
  await wait(200)

  // FOR TESTING ONLY: ?demo=empty or ?demo=error in the page address
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'error') throw new Error('The network service is not responding.')
  if (demo === 'empty') return { isSample: true, bounds: NETWORK_BOUNDS, intersections: [] }

  const study = await getIntersection()
  const intersections = [
    {
      id: study.id,
      name: study.name,
      area: study.area,
      center: study.center,
      simulation: '/current',
    },
    ...OTHER_INTERSECTIONS,
  ]
  return { isSample: true, bounds: NETWORK_BOUNDS, intersections }
}

// 24 hours of 15-minute congestion bars ending at `end` (a time in ms; now if left out)
export async function getNetworkTimeline(end = Date.now()) {
  await wait(150)
  const demo = new URLSearchParams(window.location.search).get('demo')
  return { isSample: true, bars: demo === 'empty' ? [] : sampleTimelineBars(end) }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
