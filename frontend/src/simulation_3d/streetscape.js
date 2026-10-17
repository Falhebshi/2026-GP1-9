import { SolidPolygonLayer } from '@deck.gl/layers'
import { PALETTE } from './palette'
import { material } from './materials'

// Kerbs (15 cm), raised sidewalks and medians, built by build_streetscape.py. Only for looks.
// They use the normal depth test so buildings and cars can hide them.
export function streetscapeLayers(ss, { visible = true, night = 0 } = {}) {
  const C = PALETTE.street3d
  const LIT = { ambient: 0.35, diffuse: 0.6, shininess: 4, specularColor: [20, 20, 20] }
  const layer = (kind) =>
    new SolidPolygonLayer({
      id: `streetscape-${kind}`,
      data: ss.filter((f) => f.properties.kind === kind),
      visible,
      getPolygon: (f) => f.geometry.coordinates,
      extruded: true,
      getElevation: (f) => f.properties.height_m,
      getFillColor: C[kind],
      material: LIT,
    })
  // Textured tops (pavers or concrete) drawn 3 mm above each block, so the sides keep their shading.
  const top = (kind, mat) =>
    new SolidPolygonLayer({
      id: `streetscape-${kind}-top`,
      data: ss.filter((f) => f.properties.kind === kind),
      visible,
      getPolygon: (f) =>
        f.geometry.coordinates.map((r) => r.map(([x, y]) => [x, y, f.properties.height_m + 0.003])),
      ...material(mat),
    })
  // The textured tops aren't lit, so at night we cover them with a dark layer like the street.
  const veil = new SolidPolygonLayer({
    id: 'streetscape-night-veil',
    data: ss,
    visible: visible && night > 0.01,
    getPolygon: (f) =>
      f.geometry.coordinates.map((r) => r.map(([x, y]) => [x, y, f.properties.height_m + 0.006])),
    getFillColor: [6, 10, 24, Math.round(195 * night)],
    updateTriggers: { getFillColor: night },
  })
  return [
    layer('sidewalk'),
    layer('median'),
    layer('kerb'),
    top('sidewalk', 'pavers'),
    top('median', 'concrete'),
    top('kerb', 'kerb'),
    veil,
  ]
}
