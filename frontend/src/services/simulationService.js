// Where TrafficScene3D gets the data for one intersection.
// The files live in public/data/<intersection>/ and come from our SUMO run (scripts in simulation/).
// Once the backend API is ready, only this file has to change, as long as it returns the same object.
//   network/                     roads, markings, arrows, underpass, buildings, background
//   network/signal_heads.json    where each approach's signal heads stand, and its movements
//   network/planting.geojson     plants placed by hand (optional)
//   <scenario>/run.json          the run: start time, length and its 15-minute vehicle files (optional)
//   <scenario>/signals.json      the movements' signal indications over time
//   <scenario>/vehicles_*.json   the vehicles of one 15-minute interval, see getVehicleInterval

const BASE = '/data'

async function getJson(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Could not load ${url}`)
  return response.json()
}

export async function getIntersectionScene(intersectionId, scenario = 'baseline') {
  const net = `${BASE}/${intersectionId}/network`
  const runDir = `${BASE}/${intersectionId}/${scenario}`
  const optional = (promise) => promise.catch(() => null)

  const [
    surface,
    markings,
    arrows,
    underpass,
    buildings,
    context,
    streetscape,
    detail,
    planting,
    signalHeads,
    run,
  ] = await Promise.all([
    getJson(`${net}/road_surface.geojson`),
    getJson(`${net}/road_markings.geojson`),
    getJson(`${net}/turn_arrows.geojson`),
    getJson(`${net}/underpass.geojson`),
    getJson(`${net}/buildings.geojson`),
    getJson(`${net}/context.geojson`),
    getJson(`${net}/streetscape.geojson`),
    optional(getJson(`${net}/surface_detail.geojson`)),
    optional(getJson(`${net}/planting.geojson`)),
    getJson(`${net}/signal_heads.json`),
    optional(getJson(`${runDir}/run.json`)),
  ])
  const signals = run ? await getJson(`${runDir}/${run.signals_file}`) : null

  return {
    surface,
    markings,
    arrows,
    underpass,
    buildings,
    context,
    streetscape,
    detail,
    planting,
    signalHeads,
    run,
    signals,
  }
}

// The vehicles of one 15-minute interval of a run: file is one of the names listed in run.json.
// The scene loads an interval when the playback reaches it.
export function getVehicleInterval(intersectionId, scenario, file) {
  return getJson(`${BASE}/${intersectionId}/${scenario}/${file}`)
}
