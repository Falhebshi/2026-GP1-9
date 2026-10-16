// Loads the data TrafficScene3D needs for one intersection.
// The files live in public/data/<intersection>/ and come from our SUMO run (scripts in simulation/).
// Once the backend API is ready, only this file has to change, as long as it returns the same object.
//   network/                  roads, markings, arrows, underpass, buildings, background
//   network/planting.geojson   plants placed by hand (optional)
//   <scenario>/signals.json   signal states over time
//   <scenario>/sim.json       vehicle trajectories (optional)

const BASE = '/data'

async function getJson(url) {
  const response = await fetch(url)
  if (!response.ok) throw new Error(`Could not load ${url}`)
  return response.json()
}

export async function loadIntersectionScene(intersectionId, scenario = 'baseline') {
  const net = `${BASE}/${intersectionId}/network`
  const run = `${BASE}/${intersectionId}/${scenario}`
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
    signals,
    sim,
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
    getJson(`${run}/signals.json`),
    optional(getJson(`${run}/sim.json`)),
  ])
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
    signals,
    sim,
  }
}
