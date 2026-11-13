// Where the Network Traffic Overview page gets its data.
//
// The intersections are sample data; the road congestion is synthetic (see below). When the
// backend is ready, only the inside of these functions changes; the page stays the same as long
// as the data keeps these shapes:
//
//   getNetwork()           { isSample, bounds: [[west, south], [east, north]] the map opens on,
//                            maxBounds: the same shape, how far the map can be moved and zoomed out,
//                            intersections: [{ id, name, area, center, simulation }] }
//   getNetworkTimeline(t)  { isSample, bars: [{ time, value, level }] }, the 96 bars of one day
//   getSegments(time)      GeoJSON road segments, or null without network files (see below)
//   getAvailableDays()     the days with network data, oldest first

import { getIntersection, sampleTimelineBars } from './currentTrafficService'

// Road segment congestion comes from the files in public/data/network/, built on each laptop by
// `python -m jaadah.network_congestion.synthetic` (they are not in git, because part of the
// method is derived from RCRC data). When the files are missing, getSegments returns null and
// the map shows the plain basemap, as before.
//
//   index.json              the days with data and the speed limits of the levels (HCM urban
//                           street LOS: A-B above 67 % of free flow low, C-D above 40 % moderate,
//                           E-F 40 % or less high)
//   segments.geojson        every segment's line, name, road class and lanes
//   speeds_YYYY-MM-DD.json  one per day: 96 speeds per segment (percent of free-flow speed) and
//                           one network speed per 15 minutes for the timeline
//
// getSegments(time) resolves to a GeoJSON FeatureCollection, one LineString per segment, with
//   id, name, road_class, lanes, source  from segments.geojson
//   speed       percent of free-flow speed
//   level       'low', 'moderate' or 'high' (sets the line color), or null with no data
// and `limits`, the level limits in percent of free flow, for the Heatmap view
const DATA_DIR = '/data/network'
const QUARTER_HOUR = 15 * 60 * 1000

let indexPromise = null
let segmentsPromise = null
const dayPromises = {}

function fetchJson(path) {
  return fetch(`${DATA_DIR}/${path}`).then((response) => {
    if (!response.ok) throw new Error(`${path}: ${response.status}`)
    return response.json()
  })
}

// index.json, or null when the network files have not been built on this laptop
function loadIndex() {
  indexPromise ??= fetchJson('index.json').catch(() => null)
  return indexPromise
}

function loadDay(day) {
  dayPromises[day] ??= fetchJson(`speeds_${day}.json`)
  return dayPromises[day]
}

// speed: percent of free flow
function levelOf(speed, index) {
  if (speed / 100 > index.low_above_speed_ratio) return 'low'
  if (speed / 100 > index.moderate_above_speed_ratio) return 'moderate'
  return 'high'
}

// Riyadh date (YYYY-MM-DD) and interval (0-95) of a moment, whatever the laptop's time zone
function riyadhSlot(ms) {
  const riyadh = new Date(ms + 3 * 60 * 60 * 1000)
  const day = riyadh.toISOString().slice(0, 10)
  const slot = riyadh.getUTCHours() * 4 + Math.floor(riyadh.getUTCMinutes() / 15)
  return { day, slot }
}

function slotTime(day, slot) {
  return new Date(Date.parse(`${day}T00:00:00+03:00`) + slot * QUARTER_HOUR).toISOString()
}

// The moment to show: the chosen time, or for the latest data the current 15 minutes of today
// (the last interval of the newest day when the files do not reach today)
function momentToShow(time, index) {
  const now = riyadhSlot(Date.now())
  if (!time) return index.days.includes(now.day) ? now : { day: index.days.at(-1), slot: 95 }
  const moment = riyadhSlot(Date.parse(time))
  const future = moment.day === now.day && moment.slot > now.slot
  return index.days.includes(moment.day) && !future ? moment : null
}

// The days with network data, oldest first (empty when the files have not been built)
export async function getAvailableDays() {
  const index = await loadIndex()
  return index?.days ?? []
}

// Where the page opens: null (the latest data) when the files reach today; otherwise the current
// time of day on the newest day with data. Also null without network files.
export async function getOpeningTime() {
  const index = await loadIndex()
  const now = riyadhSlot(Date.now())
  if (!index || index.days.includes(now.day)) return null
  return slotTime(index.days.at(-1), now.slot)
}

export async function getSegments(time = null) {
  const index = await loadIndex()
  if (!index) return null

  const moment = momentToShow(time, index)
  segmentsPromise ??= fetchJson('segments.geojson')
  const [segments, dayData] = await Promise.all([
    segmentsPromise,
    moment ? loadDay(moment.day) : null,
  ])

  return {
    type: 'FeatureCollection',
    // the level limits in percent of free flow, for the Heatmap view's areas
    limits: {
      lowAboveSpeed: index.low_above_speed_ratio * 100,
      moderateAboveSpeed: index.moderate_above_speed_ratio * 100,
    },
    features: segments.features.map((feature) => {
      const p = feature.properties
      const speed = dayData?.speeds[p.id]?.[moment.slot]
      const known = speed !== undefined && speed !== null
      return {
        type: 'Feature',
        geometry: feature.geometry,
        properties: {
          id: p.id,
          name: p.name_en ?? p.name_ar,
          road_class: p.road_class,
          lanes: p.lanes,
          source: p.source,
          speed: known ? speed : null,
          level: known ? levelOf(speed, index) : null,
        },
      }
    }),
  }
}

// The area the map opens on: 9 km x 4.5 km centred on the study intersection. It holds the 2 km
// square requested from RCRC with room around it, and is twice as wide as tall, the shape of the
// map area the floating cards leave free.
const NETWORK_BOUNDS = [
  [46.5891, 24.715],
  [46.6781, 24.7556],
]

// How far the map can be moved and zoomed out: the whole city, since the network view covers
// all of Riyadh. Drawn by the team around Riyadh's built-up area, reaching north to the newer
// districts. OpenStreetMap has no city boundary for Riyadh. CITY_BOX in
// jaadah/network_congestion/segments.py uses the same box.
const CITY_BOUNDS = [
  [46.51, 24.51],
  [46.94, 25.0],
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
  if (demo === 'empty')
    return { isSample: true, bounds: NETWORK_BOUNDS, maxBounds: CITY_BOUNDS, intersections: [] }

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
  return { isSample: true, bounds: NETWORK_BOUNDS, maxBounds: CITY_BOUNDS, intersections }
}

// The 96 bars of one day: the day of `end` (a time in ms) when it has network data, otherwise
// the last day with data. Without network files, 24 hours of sample bars ending at `end`.
export async function getNetworkTimeline(end = Date.now()) {
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'empty') return { isSample: true, bars: [] }

  const index = await loadIndex()
  if (!index) {
    await wait(150)
    return { isSample: true, bars: sampleTimelineBars(end) }
  }

  const wanted = riyadhSlot(end).day
  const day = index.days.includes(wanted) ? wanted : index.days.at(-1)
  const dayData = await loadDay(day)
  // bar height: how far below free flow the network is (0 free flow, 1 standstill). Today only up
  // to the current 15 minutes, like a live feed.
  const now = riyadhSlot(Date.now())
  const lastSlot = day === now.day ? now.slot : 95
  const bars = dayData.network_speed.slice(0, lastSlot + 1).map((speed, slot) => ({
    time: slotTime(day, slot),
    value: 1 - speed / 100,
    level: levelOf(speed, index),
  }))
  return { isSample: true, bars }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
