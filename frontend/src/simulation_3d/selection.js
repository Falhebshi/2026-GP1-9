import { PathLayer, SolidPolygonLayer } from '@deck.gl/layers'
import { fromM, toM } from './geo'

// How the lanes of the selected approach are shown on the 3D scene. Two styles, which can be
// combined while the team decides (TrafficScene3D reads ?highlight=colour, spotlight or both):
//   colour     the lanes glow in the approach's congestion color (from its level of service),
//              with a slow pulse
//   spotlight  the rest of the scene dims a little, and arrows run along the selected lanes in
//              the direction of travel
// Drawn every frame (the pulse and the arrows move), on top of the road but under the cars.

const DRAW_OVER = { depthCompare: 'always', depthWriteEnabled: false }
const PULSE_S = 1.6 // one pulse of the glow
const ARROW_SPACING_M = 12
const ARROW_SPEED_MPS = 9

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

// Small arrow heads every ARROW_SPACING_M along a lane centre line, moving with time t
function arrowsAlong(path, t) {
  if (!path || path.length < 2) return []
  const origin = path[0]
  const points = path.map((c) => toM(c, origin))
  const shift = (t * ARROW_SPEED_MPS) % ARROW_SPACING_M
  const arrows = []
  let walked = 0
  let next = shift
  for (let i = 1; i < points.length; i++) {
    const [ax, ay] = points[i - 1]
    const [bx, by] = points[i]
    const length = Math.hypot(bx - ax, by - ay)
    if (!length) continue
    const [fx, fy] = [(bx - ax) / length, (by - ay) / length] // direction of travel
    const [rx, ry] = [fy, -fx]
    while (next <= walked + length) {
      const k = next - walked
      const [cx, cy] = [ax + fx * k, ay + fy * k]
      const tip = [cx + fx * 1.1, cy + fy * 1.1]
      const left = [cx - fx * 0.6 - rx * 0.8, cy - fy * 0.6 - ry * 0.8]
      const right = [cx - fx * 0.6 + rx * 0.8, cy - fy * 0.6 + ry * 0.8]
      arrows.push([tip, right, left].map((p) => fromM(p, origin)))
      next += ARROW_SPACING_M
    }
    walked += length
  }
  return arrows
}

//   lanes     the selected lane features (polygons from road_surface.geojson)
//   centres   lane id -> centre line [[lon, lat], ...]
//   bounds    study area { west, south, east, north }, for the dimmed area
//   color     [r, g, b] of the approach
//   style     { colour: bool, spotlight: bool }
//   t         seconds, for the pulse and the arrows (real time, so they move when paused too)
//   night     0 (day) to 1 (night): the scene is darker at night, so the highlight is fainter
//             and mostly a thin edge, and the cars on the lanes stay easy to see
export function selectionLayers({ lanes, centres, bounds, color, style, t, night = 0 }) {
  if (!lanes?.length) return []
  const rings = lanes.map((f) => f.geometry.coordinates[0].map(([x, y]) => [x, y]))
  const layers = []

  if (style.spotlight) {
    const pad = 0.02
    const outer = [
      [bounds.west - pad, bounds.south - pad],
      [bounds.east + pad, bounds.south - pad],
      [bounds.east + pad, bounds.north + pad],
      [bounds.west - pad, bounds.north + pad],
    ]
    layers.push(
      new SolidPolygonLayer({
        id: 'selection-dim',
        data: [[outer, ...rings]], // the selected lanes are holes, so they stay as they are
        getPolygon: (d) => d,
        getFillColor: [8, 12, 24, 95],
        parameters: DRAW_OVER,
      }),
    )
  }

  if (style.colour) {
    const glow = 0.5 + 0.5 * Math.sin((2 * Math.PI * t) / PULSE_S)
    layers.push(
      new SolidPolygonLayer({
        id: 'selection-fill',
        data: rings,
        getPolygon: (d) => d,
        getFillColor: [...color, Math.round((55 + 45 * glow) * (1 - 0.75 * night))],
        parameters: DRAW_OVER,
        updateTriggers: { getFillColor: [glow, night] },
      }),
      new PathLayer({
        id: 'selection-edge',
        data: rings,
        getPath: (d) => d,
        getColor: [...color, Math.round((150 + 90 * glow) * (1 - 0.35 * night))],
        getWidth: 0.5,
        widthUnits: 'meters',
        widthMinPixels: 1.5,
        parameters: DRAW_OVER,
        updateTriggers: { getColor: [glow, night] },
      }),
    )
  }

  if (style.spotlight) {
    const arrows = lanes.flatMap((f) => arrowsAlong(centres[f.properties.id], t))
    layers.push(
      new SolidPolygonLayer({
        id: 'selection-arrows',
        data: arrows,
        getPolygon: (d) => d,
        getFillColor: style.colour ? [255, 255, 255, 230] : [...color, 235],
        parameters: DRAW_OVER,
      }),
    )
  }
  return layers
}
