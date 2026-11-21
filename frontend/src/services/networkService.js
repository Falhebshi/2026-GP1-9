// Where the Network Traffic Overview page gets its data.
//
// The intersections are sample data; the road congestion comes from the network map server (see
// below). When the
// backend is ready, only the inside of these functions changes; the page stays the same as long
// as the data keeps these shapes:
//
//   getNetwork()           { isSample, bounds: [[west, south], [east, north]] the map opens on,
//                            maxBounds: the same shape, how far the map can be moved and zoomed out,
//                            intersections: [{ id, name, area, center, simulation }] }
//   getNetworkTimeline(t)  { isSample, bars: [{ time, value, level }] }, the 96 bars of one day
//   getSegments(time)      GeoJSON road segments, or null without the network server (see below)
//   getAvailableDays()     the days with network data, oldest first; [] while the server is still
//                          filling its first interval; null when the server is not running

import { getIntersection, sampleTimelineBars } from './currentTrafficService'
import { drawnSpeeds, segmentEnds } from './segmentNeighbours'

// Road segment congestion comes from the network map server (jaadah/network_congestion/server.py),
// through the Vite proxy at /api/network (vite.config.js). It works the speeds out from the RCRC
// counts at the study intersection, so it follows the RCRC replay's clock and shows the data's own
// dates; it adds every completed 15 minutes by itself and keeps the latest day plus the 6 days
// before. Start the RCRC replay (port 8002), then the server next to `npm run dev` with
// `uvicorn jaadah.network_congestion.server:app --port 8001`.
//
//   /days              the days with data and the speed limits of the levels
//   /segments          every segment's line, name, road class and lanes
//   /speeds?time=      every segment's speed in the 15 minutes that contain time (the newest
//                      without time)
//   /timeline?day=     the network speed of each stored 15 minutes of a day
//
// Its data is not in git, because part of the method is derived from RCRC data. When the server
// is not running, getSegments returns null and the map shows the plain basemap.
//
// Levels (HCM urban street LOS by speed): A-B above 67 % of free flow low, C-D above 40 %
// moderate, E-F 40 % or less high.
//
// getSegments(time) resolves to a GeoJSON FeatureCollection, one LineString per segment, with
//   id, name, road_class, lanes, source  from /segments
//   speed       percent of free-flow speed, as drawn: short pieces and ramps are kept between
//               the speeds of the roads at their two ends (segmentNeighbours.js)
//   model_speed the server's own speed for the segment
//   level       'low', 'moderate' or 'high' (sets the line color), or null with no data
// and `limits`, the level limits in percent of free flow, for the Heatmap view, and `hasSpeeds`,
// false when the server has no stored 15 minutes for the requested time (every level is then null)
const API = '/api/network'
const QUARTER_HOUR = 15 * 60 * 1000

let segmentsPromise = null
let endsOf = null // the roads at each segment's two ends, worked out once per segment list

function fetchApi(path) {
  return fetch(`${API}/${path}`).then((response) => {
    if (!response.ok) throw new Error(`${path}: ${response.status}`)
    return response.json()
  })
}

// The days with data and the level limits, or null when the server is not running. Asked again
// each time, since the server keeps adding intervals and can be started or stopped while the page
// is open.
function loadInfo() {
  return fetchApi('days').catch(() => null)
}

// every segment's speed at a time (null = the newest interval), or null when it is not stored
function loadSpeeds(time) {
  const query = time ? `?time=${encodeURIComponent(time)}` : ''
  return fetchApi(`speeds${query}`).then(
    (result) => result.speeds,
    () => null,
  )
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

// The days with network data, oldest first: [] while the server is filling its first interval,
// null when the server is not running. Also where the speeds come from: 'rcrc' (modelled from
// the RCRC counts at the study intersection) or 'synthetic', null without the server.
export async function getAvailableDays() {
  const index = await loadInfo()
  return index ? index.days : null
}

export async function getNetworkSource() {
  const index = await loadInfo()
  return index?.source ?? null
}

// Where the page opens: null (the latest data) when the data is live, that is it reaches today or,
// for a source that runs whole weeks behind (the RCRC replay), its latest 15 minutes reach the
// current time of day; otherwise the current time of day on the newest day with data. Also null
// when the server is not running.
export async function getOpeningTime() {
  const index = await loadInfo()
  const now = riyadhSlot(Date.now())
  if (!index || !index.days.length || index.days.includes(now.day)) return null
  const latest = index.latest_interval_end && riyadhSlot(Date.parse(index.latest_interval_end))
  if (latest && latest.slot >= now.slot - 1) return null
  return slotTime(index.days.at(-1), now.slot)
}

export async function getSegments(time = null) {
  const index = await loadInfo()
  if (!index) return null

  // a failed request is not kept, so the next call asks again
  segmentsPromise ??= fetchApi('segments').catch((err) => {
    segmentsPromise = null
    throw err
  })
  const [segments, speeds] = await Promise.all([segmentsPromise, loadSpeeds(time)])
  if (endsOf?.segments !== segments) endsOf = { segments, ends: segmentEnds(segments.features) }
  const own = segments.features.map((f) => speeds?.[f.properties.id] ?? null)
  const drawn = drawnSpeeds(own, endsOf.ends)

  return {
    type: 'FeatureCollection',
    hasSpeeds: speeds !== null,
    // the level limits in percent of free flow, for the Heatmap view's areas
    limits: {
      lowAboveSpeed: index.low_above_speed_ratio * 100,
      moderateAboveSpeed: index.moderate_above_speed_ratio * 100,
    },
    features: segments.features.map((feature, i) => {
      const p = feature.properties
      const speed = drawn[i]
      const known = speed !== null
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
          model_speed: own[i],
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

// The bars of one day: the day of `end` (a time in ms) when it has network data, otherwise the
// last day with data; none while the server fills its first interval. Without the network server,
// 24 hours of sample bars ending at `end`.
export async function getNetworkTimeline(end = Date.now()) {
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'empty') return { isSample: true, bars: [] }

  const index = await loadInfo()
  if (!index) {
    await wait(150)
    return { isSample: true, bars: sampleTimelineBars(end) }
  }

  // the server is still filling its first interval: no bars yet
  if (!index.days.length) return { isSample: true, bars: [] }

  const wanted = riyadhSlot(end).day
  const day = index.days.includes(wanted) ? wanted : index.days.at(-1)

  // bar height: how far below free flow the network is (0 free flow, 1 standstill). The server
  // has only completed 15 minutes, so today ends at the latest one, like a live feed.
  const { intervals } = await fetchApi(`timeline?day=${day}`)
  const bars = intervals.map((interval) => ({
    time: new Date(interval.interval_start).toISOString(),
    value: 1 - interval.network_speed / 100,
    level: levelOf(interval.network_speed, index),
  }))
  return { isSample: true, bars }
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}
