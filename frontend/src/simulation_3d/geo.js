// Convert between lon/lat and local metres around a point. Good enough (under 0.1% error) for our small area.
const LAT0 = 24.735
export const M_PER_DEG_LON = 111320 * Math.cos((LAT0 * Math.PI) / 180)
export const M_PER_DEG_LAT = 110540

export const toM = ([lon, lat], [olon, olat]) => [
  (lon - olon) * M_PER_DEG_LON,
  (lat - olat) * M_PER_DEG_LAT,
]
export const fromM = ([x, y], [olon, olat]) => [olon + x / M_PER_DEG_LON, olat + y / M_PER_DEG_LAT]

// bits of dash cut off at the end of a line, too short to read as a dash
const MIN_DASH_M = 1
const run = (line) =>
  line.slice(1).reduce((s, q, i) => s + Math.hypot(q[0] - line[i][0], q[1] - line[i][1]), 0)

// Split a [lon,lat,z] line into dashes. dash and gap are in metres.
// The pattern doesn't start at the beginning of each line: it is lined up with a fixed origin, by
// where the line's start falls along its own direction. So the dashes of neighbouring lanes sit
// side by side in rows, and stay in step where a road is split into several pieces.
export function dashLine(coords, dash, gap, origin = coords[0]) {
  const pts = coords.map((c) => [...toM(c, origin), c[2] ?? 0])
  const out = []
  const [a, b] = [pts[0], pts.find((q) => q[0] !== pts[0][0] || q[1] !== pts[0][1]) ?? pts[0]]
  const len = Math.hypot(b[0] - a[0], b[1] - a[1]) || 1
  const period = dash + gap
  const start = (a[0] * (b[0] - a[0]) + a[1] * (b[1] - a[1])) / len
  const phase = ((start % period) + period) % period
  let cur = [],
    on = phase < dash,
    left = phase < dash ? dash - phase : period - phase
  for (let k = 0; k < pts.length - 1; k++) {
    let [x1, y1, z1] = pts[k]
    const [x2, y2, z2] = pts[k + 1]
    let seg = Math.hypot(x2 - x1, y2 - y1)
    if (!seg) continue
    const ux = (x2 - x1) / seg,
      uy = (y2 - y1) / seg,
      uz = (z2 - z1) / seg
    while (seg > 1e-9) {
      const step = Math.min(left, seg)
      const nx = x1 + ux * step,
        ny = y1 + uy * step,
        nz = z1 + uz * step
      if (on) {
        if (!cur.length) cur.push([x1, y1, z1])
        cur.push([nx, ny, nz])
      }
      x1 = nx
      y1 = ny
      z1 = nz
      seg -= step
      left -= step
      if (left <= 1e-9) {
        if (on && cur.length > 1 && run(cur) > MIN_DASH_M) out.push(cur)
        cur = []
        on = !on
        left = on ? dash : gap
      }
    }
  }
  if (cur.length > 1 && run(cur) > MIN_DASH_M) out.push(cur)
  return out.map((s) => s.map(([x, y, z]) => [...fromM([x, y], origin), z]))
}

// How many metres one screen pixel covers at this zoom (deck.gl uses 512 px tiles).
export const metersPerPixel = (lat, zoom) =>
  (40075016.686 * Math.cos((lat * Math.PI) / 180)) / (512 * 2 ** zoom)

// Shift a [lon,lat,z] line sideways by d metres (positive is to the left). Works well for gentle curves.
export function offsetPath(coords, d) {
  if (coords.length < 2) return coords
  const o = coords[0]
  const P = coords.map((c) => toM(c, o))
  return coords.map((c, i) => {
    const a = P.at(Math.max(0, i - 1)),
      b = P.at(Math.min(P.length - 1, i + 1))
    let nx = -(b[1] - a[1]),
      ny = b[0] - a[0]
    const L = Math.hypot(nx, ny) || 1
    nx /= L
    ny /= L
    const [x, y] = P.at(i)
    return [...fromM([x + nx * d, y + ny * d], o), c[2] ?? 0]
  })
}
