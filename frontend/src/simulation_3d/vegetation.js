import { SimpleMeshLayer } from '@deck.gl/mesh-layers'
import { toM, fromM } from './geo'
import { PALM_TRUNK, PALM_CROWN, SHRUB, TREE_CROWN, TREE_TRUNK } from './meshes'

// Trees and planting, laid out in regular patterns like a landscape plan (not surveyed):
//  - date palms in rows straight across each road, every 24 m out to the edge of the study area,
//    one on each median and sidewalk the row crosses. The rows are at the same distances on all
//    four approaches, and both sides of a road always have the same number of palms. A low shrub
//    sits halfway between rows on the medians.
//  - shade trees in rows around the edge of every parking lot
//  - trees on a regular grid in the green areas from OpenStreetMap
// Nothing over the tunnel, near the junction centre or the signals, so the traffic stays visible.
// Extra plants can be placed by hand in public/data/<intersection>/network/planting.geojson: one
// point per plant with a "type" of "palm", "shrub" or "tree".
const PALM_FIRST_M = 40 // distance of the first palm from the junction centre
const PALM_SPACING_M = 24
const PALM_LAST_M = 500 // the far corners of the study square
const CENTRE_M = 4 // a plant this close to the road's centre line is on the centre median
const ROAD_HALF_WIDTH_M = 60 // plants further out belong to other streets
const CLEAR_OF_JUNCTION_M = 32 // no planting this close to the junction centre
const CLEAR_OF_SIGNALS_M = 7
const PARKING_TREE_SPACING_M = 10
const GREEN_GRID_M = 9

// same numbers on every load, so trees don't jump around between reloads
function seeded(seed) {
  let s = seed >>> 0
  return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296
}

function inside([x, y], ring) {
  let c = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i],
      [xj, yj] = ring[j]
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c
  }
  return c
}

// Main direction of a long, thin polygon (principal axis of its points), with its extent
function axisOf(ring) {
  const n = ring.length
  const mx = ring.reduce((s, p) => s + p[0], 0) / n
  const my = ring.reduce((s, p) => s + p[1], 0) / n
  let sxx = 0,
    syy = 0,
    sxy = 0
  for (const [x, y] of ring) {
    sxx += (x - mx) ** 2
    syy += (y - my) ** 2
    sxy += (x - mx) * (y - my)
  }
  const angle = 0.5 * Math.atan2(2 * sxy, sxx - syy)
  const ux = Math.cos(angle),
    uy = Math.sin(angle)
  const along = ring.map(([x, y]) => (x - mx) * ux + (y - my) * uy)
  const across = ring.map(([x, y]) => -(x - mx) * uy + (y - my) * ux)
  return {
    mx,
    my,
    ux,
    uy,
    min: Math.min(...along),
    max: Math.max(...along),
    width: Math.max(...across) - Math.min(...across),
  }
}

// Centre line of a long, thin polygon: walk along its main direction and, every metre, take the
// middle of the polygon across it. Follows bends and narrowing ends, unlike the straight axis.
function centreLine(ring) {
  const ax = axisOf(ring)
  const nx = -ax.uy,
    ny = ax.ux
  const line = []
  for (let s = ax.min; s <= ax.max; s += 1) {
    const cx = ax.mx + ax.ux * s,
      cy = ax.my + ax.uy * s
    const hits = []
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [x1, y1] = ring[j],
        [x2, y2] = ring[i]
      // where the cross line (c + t * n) meets this edge
      const dx = x2 - x1,
        dy = y2 - y1
      const den = nx * dy - ny * dx
      if (Math.abs(den) < 1e-9) continue
      const t = ((x1 - cx) * dy - (y1 - cy) * dx) / den
      const k = ((x1 - cx) * ny - (y1 - cy) * nx) / den
      if (k >= 0 && k <= 1) hits.push(t)
    }
    if (hits.length < 2) continue
    const lo = Math.min(...hits),
      hi = Math.max(...hits)
    line.push({ p: [cx + nx * ((lo + hi) / 2), cy + ny * ((lo + hi) / 2)], width: hi - lo })
  }
  return line
}

export function prepareVegetation({ streetscape, context, signals, center, roofs, planting }) {
  const random = seeded(7)
  const signalPoints = (signals?.controllers ?? []).flatMap((c) =>
    c.approaches.flatMap((a) => [a.pole, ...a.heads.map((h) => a.P(h.m))]),
  )
  const signalM = signalPoints.map((p) => toM(p, center))
  const roofRings = (roofs ?? []).map((f) => f.geometry.coordinates[0].map((c) => toM(c, center)))
  const clear = (p) =>
    Math.hypot(p[0], p[1]) > CLEAR_OF_JUNCTION_M &&
    signalM.every((s) => Math.hypot(p[0] - s[0], p[1] - s[1]) > CLEAR_OF_SIGNALS_M) &&
    !roofRings.some((r) => inside(p, r))

  const palms = []
  const shrubs = []
  const strips = []
  for (const f of streetscape ?? []) {
    const kind = f.properties.kind
    if (kind !== 'median' && kind !== 'sidewalk') continue
    const ring = f.geometry.coordinates[0].map((c) => toM(c, center))
    strips.push({ kind, ring, line: centreLine(ring), z: f.properties.height_m })
  }

  // Each row of plants goes straight across the road. The row starts on the centre median, where
  // its centre line crosses a fixed distance from the junction (40 m, 52 m, 64 m ...), so every
  // arm has rows at the same distances. From there it runs square to the road, and gets a plant
  // where it crosses each median or sidewalk. Even rows are palms, odd rows shrubs (medians only).
  const stations = []
  for (let d = PALM_FIRST_M; d <= PALM_LAST_M; d += PALM_SPACING_M / 2) stations.push(d)
  const starts = []
  for (const s of strips) {
    if (s.kind !== 'median') continue
    for (let i = 1; i < s.line.length; i++) {
      const a = s.line[i - 1].p,
        b = s.line[i].p
      const da = Math.hypot(...a),
        db = Math.hypot(...b)
      stations.forEach((d, n) => {
        if ((da - d) * (db - d) > 0 || da === db) return
        const k = (d - da) / (db - da)
        const p = [a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k]
        const len = Math.hypot(b[0] - a[0], b[1] - a[1])
        starts.push({ n, p, dir: [(b[0] - a[0]) / len, (b[1] - a[1]) / len] })
      })
    }
  }
  // the centre median is the one closest to the line from the junction out along the road
  // the roads leave the junction diagonally, so each arm sits in one quarter (NE, SE, SW, NW)
  const armOf = ([x, y]) => Math.floor(((Math.atan2(x, y) * 180) / Math.PI + 360) / 90) % 4
  const centres = new Map()
  for (const c of starts) {
    const key = `${c.n}|${armOf(c.p)}`
    const off = Math.abs(c.p[0] * c.dir[1] - c.p[1] * c.dir[0])
    if (!centres.has(key) || off < centres.get(key).off) centres.set(key, { ...c, off })
  }

  for (const { n, p, dir } of centres.values()) {
    const across = [-dir[1], dir[0]]
    // where the line across the road meets the centre line of each strip
    const hits = []
    for (const s of strips) {
      if (n % 2 === 1 && s.kind !== 'median') continue
      for (let i = 1; i < s.line.length; i++) {
        const a = s.line[i - 1],
          b = s.line[i]
        const ex = b.p[0] - a.p[0],
          ey = b.p[1] - a.p[1]
        const den = across[0] * ey - across[1] * ex
        if (Math.abs(den) < 1e-9) continue
        const t = ((a.p[0] - p[0]) * ey - (a.p[1] - p[1]) * ex) / den
        const k = ((a.p[0] - p[0]) * across[1] - (a.p[1] - p[1]) * across[0]) / den
        if (k < 0 || k > 1 || Math.abs(t) > ROAD_HALF_WIDTH_M) continue
        const q = [p[0] + across[0] * t, p[1] + across[1] * t]
        const width = a.width + (b.width - a.width) * k
        if (width < (n % 2 ? 2.2 : 1.4) || !inside(q, s.ring) || !clear(q)) continue
        hits.push({ t, q, z: s.z })
      }
    }
    // rows counted outwards from the centre on each side; keep one only if the other side has
    // one at the same count, so both sides of the road match
    const centre = hits.filter((h) => Math.abs(h.t) < CENTRE_M).slice(0, 1)
    const left = hits.filter((h) => h.t >= CENTRE_M).sort((a, b) => a.t - b.t)
    const right = hits.filter((h) => h.t <= -CENTRE_M).sort((a, b) => b.t - a.t)
    const rows = Math.min(left.length, right.length)
    for (const h of [...centre, ...left.slice(0, rows), ...right.slice(0, rows)]) {
      if (n % 2 === 1) shrubs.push({ position: fromM(h.q, center), size: 0.8, z: h.z })
      else
        palms.push({
          position: fromM(h.q, center),
          height: 7.5,
          size: 1,
          turn: (n * 37) % 360,
          z: h.z,
        })
    }
  }

  const trees = []
  for (const f of context?.areas ?? []) {
    const ring = f.geometry.coordinates[0].map((c) => toM(c, center))
    // parking lots: a row of shade trees just inside the edge
    if (f.properties.class === 'parking') {
      for (let i = 0; i < ring.length - 1; i++) {
        const [a, b] = [ring[i], ring[i + 1]]
        const len = Math.hypot(b[0] - a[0], b[1] - a[1])
        const ux = (b[0] - a[0]) / len,
          uy = (b[1] - a[1]) / len
        for (let d = PARKING_TREE_SPACING_M / 2; d < len; d += PARKING_TREE_SPACING_M) {
          // step 1.5 m inwards: try both sides and keep the one inside the lot
          for (const side of [1, -1]) {
            const p = [a[0] + ux * d - uy * 1.5 * side, a[1] + uy * d + ux * 1.5 * side]
            if (inside(p, ring)) {
              if (clear(p)) trees.push({ position: fromM(p, center), height: 5, size: 0.8 })
              break
            }
          }
        }
      }
    }
    // green areas: trees on a grid, kept 2.5 m from the edge
    if (f.properties.class === 'green') {
      const xs = ring.map((p) => p[0]),
        ys = ring.map((p) => p[1])
      for (let x = Math.min(...xs) + GREEN_GRID_M / 2; x < Math.max(...xs); x += GREEN_GRID_M)
        for (let y = Math.min(...ys) + GREEN_GRID_M / 2; y < Math.max(...ys); y += GREEN_GRID_M) {
          const p = [x, y]
          const deep = [
            [2.5, 0],
            [-2.5, 0],
            [0, 2.5],
            [0, -2.5],
          ].every(([dx, dy]) => inside([x + dx, y + dy], ring))
          if (deep && clear(p))
            trees.push({ position: fromM(p, center), height: 5.5, size: 0.9 + ((x + y) % 3) * 0.1 })
        }
    }
  }

  // plants placed by hand
  const shrubs2 = []
  for (const f of planting?.features ?? []) {
    if (f.geometry?.type !== 'Point') continue
    const [lon, lat] = f.geometry.coordinates
    const type = f.properties?.type
    const size = f.properties?.size ?? 0.8 + random() * 0.4
    if (type === 'palm')
      palms.push({
        position: [lon, lat],
        height: 6.5 + random() * 2.5,
        size,
        turn: random() * 360,
        z: 0,
      })
    else if (type === 'shrub') shrubs2.push({ position: [lon, lat], size, z: 0 })
    else if (type === 'tree') trees.push({ position: [lon, lat], height: 4 + random() * 3, size })
  }
  return { palms, shrubs: [...shrubs, ...shrubs2], trees }
}

const FOLIAGE = { ambient: 0.5, diffuse: 0.55, shininess: 6, specularColor: [20, 26, 20] }
const WHITE = [255, 255, 255]

export function vegetationLayers(veg, { visible = true } = {}) {
  if (!veg) return []
  const at = (d, dz) => [...d.position, (d.z ?? 0) + dz]
  return [
    new SimpleMeshLayer({
      id: 'palm-trunks',
      data: veg.palms,
      visible,
      mesh: PALM_TRUNK,
      getPosition: (d) => at(d, 0),
      getScale: (d) => [d.height, d.height, d.height],
      getColor: WHITE,
      material: FOLIAGE,
    }),
    new SimpleMeshLayer({
      id: 'palm-crowns',
      data: veg.palms,
      visible,
      mesh: PALM_CROWN,
      getPosition: (d) => at(d, d.height),
      getOrientation: (d) => [0, d.turn, 0],
      getScale: (d) => [d.size, d.size, d.size],
      getColor: WHITE,
      material: FOLIAGE,
    }),
    new SimpleMeshLayer({
      id: 'shrubs',
      data: veg.shrubs,
      visible,
      mesh: SHRUB,
      getPosition: (d) => at(d, 0.4 * d.size),
      getOrientation: (d) => [0, ((d.position[0] * 1e6) % 360) | 0, 0],
      getScale: (d) => [0.75 * d.size, 0.75 * d.size, 0.55 * d.size],
      getColor: WHITE,
      material: FOLIAGE,
    }),
    new SimpleMeshLayer({
      id: 'tree-trunks',
      data: veg.trees,
      visible,
      mesh: TREE_TRUNK,
      getPosition: (d) => [...d.position, 0],
      getScale: (d) => [1, 1, d.height * 0.55],
      getColor: WHITE,
      material: FOLIAGE,
    }),
    new SimpleMeshLayer({
      id: 'tree-crowns',
      data: veg.trees,
      visible,
      mesh: TREE_CROWN,
      getPosition: (d) => [...d.position, d.height * 0.72],
      getOrientation: (d) => [0, ((d.position[1] * 1e6) % 360) | 0, 0],
      getScale: (d) => [2.1 * d.size, 2.1 * d.size, 1.7 * d.size],
      getColor: WHITE,
      material: FOLIAGE,
    }),
  ]
}
