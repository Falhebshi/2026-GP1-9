import { PathLayer, SolidPolygonLayer } from '@deck.gl/layers'

// How the lanes of the selected approach are shown on the 3D scene: a light tint in the approach's
// congestion color (from its level of service) with a slow, gentle pulse, kept faint so the eye
// stays on the traffic.
// Drawn every frame (the pulse moves), on top of the road but under the cars.

const DRAW_OVER = { depthCompare: 'always', depthWriteEnabled: false }
const PULSE_S = 3.2 // one pulse of the glow

// Level of service to congestion level, with the colors of the traffic timeline (index.css)
const LEVEL_OF = { A: 'low', B: 'low', C: 'moderate', D: 'moderate', E: 'high', F: 'high' }

function cssColor(name) {
  const hex = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  const value = hex.startsWith('#') ? hex.slice(1) : ''
  if (value.length !== 6) return [86, 132, 196]
  return [0, 2, 4].map((i) => parseInt(value.slice(i, i + 2), 16))
}

// The color of an approach: its congestion level, or the theme's selection color without a grade
export function approachColor(grade) {
  const level = LEVEL_OF[grade]
  return cssColor(level ? `--congestion-${level}` : '--color-selected')
}

//   lanes   the selected lane features (polygons from road_surface.geojson)
//   color   [r, g, b] of the approach
//   t       seconds, for the pulse (real time, so it moves when paused too)
//   night   0 (day) to 1 (night): the scene is darker at night, so the highlight is fainter and
//           mostly a thin edge, and the cars on the lanes stay easy to see
export function selectionLayers({ lanes, color, t, night = 0 }) {
  if (!lanes?.length) return []
  const rings = lanes.map((f) => f.geometry.coordinates[0].map(([x, y]) => [x, y]))
  const glow = 0.5 + 0.5 * Math.sin((2 * Math.PI * t) / PULSE_S)

  return [
    new SolidPolygonLayer({
      id: 'selection-fill',
      data: rings,
      getPolygon: (d) => d,
      getFillColor: [...color, Math.round((30 + 10 * glow) * (1 - 0.75 * night))],
      parameters: DRAW_OVER,
      updateTriggers: { getFillColor: [glow, night] },
    }),
    new PathLayer({
      id: 'selection-edge',
      data: rings,
      getPath: (d) => d,
      getColor: [...color, Math.round((120 + 30 * glow) * (1 - 0.35 * night))],
      getWidth: 0.5,
      widthUnits: 'meters',
      widthMinPixels: 1.5,
      parameters: DRAW_OVER,
      updateTriggers: { getColor: [glow, night] },
    }),
  ]
}
