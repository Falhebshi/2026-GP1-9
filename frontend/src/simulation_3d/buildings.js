import { PolygonLayer, SolidPolygonLayer } from '@deck.gl/layers'
import { toM } from './geo'
import { PALETTE, glowMaterial } from './palette'
import { material } from './materials'

// Buildings around the intersection, from OSM, Overture Maps and 8 landmarks traced from Esri imagery
// (see data/sumo_run/merge_buildings.py). Only 6 have real floor counts in OSM, the rest are estimated heights.
// 3D view shows modern blocks with a glass window band on every floor, Top view shows flat
// footprints like a site plan. At night some of the windows are lit.
const NEAR_M = 0
const FLOOR_M = 3.5 // one storey
const WINDOW_M = 1.4 // height of the glass band on each floor

export function prepareBuildings(geojson, center) {
  const near = [],
    far = []
  for (const f of geojson.features) {
    const ring = f.geometry.coordinates[0]
    let sx = 0,
      sy = 0
    for (const c of ring) {
      const [x, y] = toM(c, center)
      sx += x
      sy += y
    }
    const dist = Math.hypot(sx / ring.length, sy / ring.length)
    ;(dist < NEAR_M ? near : far).push(f)
  }
  return { near, far, windows: windowBands(far), count: geojson.features.length }
}

// One glass band per floor, slightly outside the wall so it doesn't flicker against it.
// lit: about 40% of the bands are lit at night, picked from the building id so it stays the same.
function windowBands(buildings) {
  const bands = []
  for (const f of buildings) {
    if (f.properties.base_m) continue
    const height = f.properties.height_m ?? 7
    const ring = f.geometry.coordinates[0]
    const cx = ring.reduce((s, c) => s + c[0], 0) / ring.length
    const cy = ring.reduce((s, c) => s + c[1], 0) / ring.length
    const size = Math.max(...ring.map((c) => Math.hypot(c[0] - cx, c[1] - cy))) || 1e-6
    const grow = 1 + 0.15 / 111000 / size // about 15 cm outwards
    const outset = ring.map(([x, y]) => [cx + (x - cx) * grow, cy + (y - cy) * grow])
    const seed = hash(f)
    for (let z = 1.0; z + WINDOW_M <= height - 0.8; z += FLOOR_M) {
      bands.push({
        polygon: outset.map(([x, y]) => [x, y, z]),
        lit: (seed + Math.round(z * 7)) % 5 < 2,
      })
    }
  }
  return bands
}

function hash(f) {
  const id = String(f.properties.osm_id || f.properties.name || f.geometry.coordinates[0][0][0])
  let h = 0
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return h
}

// Pick a facade color from the building id, so it stays the same after a reload.
const facade = (f) => {
  return PALETTE.facades.at(hash(f) % PALETTE.facades.length)
}

export function buildingLayers(b, { top = false, night = 0 } = {}) {
  // Top view footprints are unlit, so we darken them for night ourselves.
  const dim = (c) =>
    c.map((v, i) => Math.round(v * (1 - 0.78 * night) + [6, 10, 24].at(i) * 0.78 * night))
  const { wall, roofLine, flat } = PALETTE.building
  const common = {
    // Raised structures like the pedestrian bridge canopies start at base_m above the ground.
    getPolygon: (f) =>
      f.properties.base_m
        ? f.geometry.coordinates.map((r) => r.map(([x, y]) => [x, y, f.properties.base_m]))
        : f.geometry.coordinates,
    extruded: !top,
    wireframe: false,
    pickable: false, // buildings don't react to the mouse
    getElevation: (f) => f.properties.height_m ?? 7,
    stroked: top,
    lineWidthUnits: 'meters',
    getLineWidth: 0.35,
    lineWidthMinPixels: 0.5,
    // outlines darken at night like the footprints, so they don't glow white
    getLineColor: dim(roofLine),
    material: { ambient: 0.4, diffuse: 0.55, shininess: 12, specularColor: [40, 40, 40] },
  }
  return [
    // In Top view the canopies are half transparent so the lanes under them stay visible.
    new PolygonLayer({
      id: 'buildings',
      data: b.far,
      ...common,
      getFillColor: (f) =>
        top ? (f.properties.base_m ? [...dim(facade(f)), 110] : dim(facade(f))) : facade(f),
      updateTriggers: { getFillColor: [top, night], getLineColor: night },
    }),
    // Glass window bands: blue-grey and shiny by day; at night the lit ones glow warm
    new SolidPolygonLayer({
      id: 'building-windows',
      data: b.windows,
      visible: !top,
      getPolygon: (d) => d.polygon,
      extruded: true,
      getElevation: WINDOW_M,
      getFillColor: [124, 142, 156],
      material: { ambient: 0.42, diffuse: 0.45, shininess: 60, specularColor: [120, 130, 140] },
    }),
    new SolidPolygonLayer({
      id: 'building-windows-lit',
      data: b.windows.filter((d) => d.lit),
      visible: !top && night > 0.3,
      getPolygon: (d) => d.polygon,
      extruded: true,
      getElevation: WINDOW_M,
      getFillColor: [255, 214, 150],
      opacity: Math.min(1, (night - 0.3) / 0.4),
      material: glowMaterial(0.9),
    }),
    // Flat concrete roofs, drawn as a thin textured layer on top of each block.
    new SolidPolygonLayer({
      id: 'building-roofs',
      data: b.far.filter((f) => !f.properties.base_m),
      visible: !top,
      getPolygon: (f) =>
        f.geometry.coordinates.map((r) =>
          r.map(([x, y]) => [x, y, (f.properties.height_m ?? 7) + 0.03]),
        ),
      ...material('concrete'),
    }),
    new SolidPolygonLayer({
      id: 'building-roofs-night',
      data: b.far.filter((f) => !f.properties.base_m),
      visible: !top && night > 0.01,
      getPolygon: (f) =>
        f.geometry.coordinates.map((r) =>
          r.map(([x, y]) => [x, y, (f.properties.height_m ?? 7) + 0.05]),
        ),
      getFillColor: [6, 10, 24, Math.round(195 * night)],
      updateTriggers: { getFillColor: night },
    }),
    new PolygonLayer({
      id: 'buildings-near',
      data: b.near,
      ...common,
      getFillColor: top ? flat : [...wall, 95],
      parameters: top ? {} : { depthWriteEnabled: false },
    }),
  ]
}
