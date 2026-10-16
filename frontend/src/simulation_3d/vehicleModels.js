// Car models built in code: sedan, SUV, crossover, pickup and Defender, with the sizes of cars that
// are common on Riyadh roads (Camry, Land Cruiser, RAV4, Sierra, Defender). Metres; x forward
// from the middle of the car, y to the left, z up from the road.
//
// The body is a loft: cross sections along the car, each a rounded shape that is widest at the
// shoulder and tucks in at the bottom and the top, so the sides curve like real panels. The cabin
// (glass and roof) is a second loft on top of it. Normals are smoothed across each loft, so light
// rolls over the bodywork instead of showing flat facets.
//
// Every model is split by material so each part gets its own colour and shine:
//   paint     body and roof (white here, tinted with the car's colour by the layer)
//   shiny     glass, wheel rims, number plates
//   matte     tyres, wheel arches, black plastic, grilles
//   head, tail, brake, indicatorLeft, indicatorRight   the lamps, drawn on top when they are lit

const rgb = (r, g, b) => [r / 255, g / 255, b / 255]
const WHITE = [1, 1, 1]
const GLASS = rgb(30, 38, 48)
const RUBBER = rgb(30, 30, 32)
const ARCH = rgb(16, 16, 18)
const PLASTIC = rgb(40, 41, 44)
const GRILLE = rgb(26, 27, 30)
const RIM = rgb(176, 180, 186)
const RIM_DARK = rgb(52, 54, 58)
const PLATE = rgb(232, 232, 228)
const BED = rgb(36, 36, 38)
const RAIL = rgb(58, 60, 64)
const LAMP_FRONT = rgb(205, 210, 214)
const LAMP_REAR = rgb(110, 22, 24)

const SE = 2.6 // how square the body sections are (2 = ellipse, higher = boxier); a model can set its own
const clamp01 = (v) => Math.min(1, Math.max(0, v))

// A list of triangles with normals and vertex colours, in the form SimpleMeshLayer takes.
function part() {
  const positions = [],
    normals = [],
    colors = []
  const add = (pts, nrm, color) => {
    for (let i = 0; i < 3; i++) {
      positions.push(...pts[i])
      normals.push(...nrm[i])
      colors.push(...color)
    }
  }
  // triangle with one flat normal, turned to face `out` (a direction) if given
  const tri = (a, b, c, color, out) => {
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]],
      v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]]
    let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    const len = Math.hypot(...n)
    if (len < 1e-12) return
    n = n.map((x) => x / len)
    if (out && n[0] * out[0] + n[1] * out[1] + n[2] * out[2] < 0) n = n.map((x) => -x)
    add([a, b, c], [n, n, n], color)
  }
  const quad = (a, b, c, d, color, out) => {
    tri(a, b, c, color, out)
    tri(a, c, d, color, out)
  }
  const done = () => ({
    positions: { size: 3, value: new Float32Array(positions) },
    normals: { size: 3, value: new Float32Array(normals) },
    colors: { size: 3, value: new Float32Array(colors) },
  })
  return { add, tri, quad, done, positions, normals, colors }
}

// Smooth curve through key values (monotone cubic, so it never overshoots between keys).
function smoothTrack(keys, field) {
  const xs = keys.map((k) => k.x),
    ys = keys.map((k) => k[field])
  const n = xs.length
  const d = []
  for (let i = 0; i < n - 1; i++) d.push((ys[i + 1] - ys[i]) / (xs[i + 1] - xs[i]))
  const m = ys.map((_, i) => {
    if (i === 0) return d[0]
    if (i === n - 1) return d[n - 2]
    if (d[i - 1] * d[i] <= 0) return 0
    return 2 / (1 / d[i - 1] + 1 / d[i])
  })
  return (x) => {
    if (x <= xs[0]) return ys[0]
    if (x >= xs[n - 1]) return ys[n - 1]
    let i = 0
    while (xs[i + 1] < x) i++
    const h = xs[i + 1] - xs[i],
      t = (x - xs[i]) / h
    const t2 = t * t,
      t3 = t2 * t
    return (
      (2 * t3 - 3 * t2 + 1) * ys[i] +
      (t3 - 2 * t2 + t) * h * m[i] +
      (-2 * t3 + 3 * t2) * ys[i + 1] +
      (t3 - t2) * h * m[i + 1]
    )
  }
}

// Straight lines between keys (for the glass, so windscreens stay flat).
function linearTrack(keys, field) {
  return (x) => {
    if (x <= keys[0].x) return keys[0][field]
    for (let i = 1; i < keys.length; i++)
      if (x <= keys[i].x) {
        const a = keys[i - 1],
          b = keys[i]
        return a[field] + ((b[field] - a[field]) * (x - a.x)) / (b.x - a.x)
      }
    return keys.at(-1)[field]
  }
}

// Body section at any x, from the model's keys. Fields:
//   hw  half width at the shoulder        zs  height of the shoulder
//   wb  half width at the bottom          zb  height of the underside
//   wt  half width where the top starts   zt  height of the top (bonnet, boot, waist)
function bodyAt(model) {
  const tuck = model.tuck ?? 0.14 // how far the top of the body is tucked in from the shoulder
  const keys = model.body.map((k) => ({
    wb: k.hw - 0.07,
    wt: k.hw - tuck,
    ...k,
  }))
  const tracks = Object.fromEntries(
    ['hw', 'wb', 'wt', 'zb', 'zs', 'zt'].map((f) => [f, smoothTrack(keys, f)]),
  )
  const se = model.boxy ?? SE
  return (x) => ({ ...Object.fromEntries(Object.entries(tracks).map(([f, tr]) => [f, tr(x)])), se })
}

// Half width of a body section at height z (a superellipse above and below the shoulder).
function halfWidth(k, z) {
  if (z <= k.zs) {
    const t = clamp01((k.zs - z) / (k.zs - k.zb))
    return k.wb + (k.hw - k.wb) * Math.pow(1 - Math.pow(t, k.se), 1 / k.se)
  }
  const t = clamp01((z - k.zs) / (k.zt - k.zs))
  return k.wt + (k.hw - k.wt) * Math.pow(1 - Math.pow(t, k.se), 1 / k.se)
}

// Points around one half of a body section, bottom middle to top middle, as [y, z].
function bodyHalfRing(k) {
  const pw = (v) => Math.pow(Math.abs(v), 2 / k.se)
  const pts = [
    [0, k.zb],
    [k.wb * 0.5, k.zb],
  ]
  const STEPS = 7
  for (let i = 0; i <= STEPS; i++) {
    const a = ((i / STEPS) * Math.PI) / 2
    pts.push([k.wb + (k.hw - k.wb) * pw(Math.sin(a)), k.zs - (k.zs - k.zb) * pw(Math.cos(a))])
  }
  for (let i = 1; i <= STEPS; i++) {
    const a = ((i / STEPS) * Math.PI) / 2
    pts.push([k.wt + (k.hw - k.wt) * pw(Math.cos(a)), k.zs + (k.zt - k.zs) * pw(Math.sin(a))])
  }
  pts.push([k.wt * 0.5, k.zt + 0.02], [0, k.zt + 0.025])
  return pts
}

// Full ring from a half ring: right side (negative y) bottom to top, then the left side back down.
function fullRing(half) {
  const right = half.map(([y, z]) => [-y, z])
  const left = half
    .slice(1, -1)
    .reverse()
    .map(([y, z]) => [y, z])
  return [...right, ...left]
}

// Lofts rings (one per x) into a smooth surface. pick(i, j) says which part and colour each
// quad goes to (or null to leave it out); quad (i, j) runs from ring i to i+1, point j to j+1.
function loft(xs, rings, centreZ, pick) {
  const P = xs.map((x, i) => rings[i].map(([y, z]) => [x, y, z]))
  const nI = P.length,
    nJ = P[0].length
  const N = P.map((row, i) =>
    row.map((p, j) => {
      const a = P[Math.min(i + 1, nI - 1)][j],
        b = P[Math.max(i - 1, 0)][j]
      const c = row[(j + 1) % nJ],
        d = row[(j - 1 + nJ) % nJ]
      const u = [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
        v = [c[0] - d[0], c[1] - d[1], c[2] - d[2]]
      let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
      const out = [0, p[1], p[2] - centreZ]
      if (n[0] * out[0] + n[1] * out[1] + n[2] * out[2] < 0) n = n.map((x) => -x)
      const len = Math.hypot(...n) || 1
      return n.map((x) => x / len)
    }),
  )
  for (let i = 0; i < nI - 1; i++)
    for (let j = 0; j < nJ; j++) {
      const j2 = (j + 1) % nJ
      const target = pick(i, j, (xs[i] + xs[i + 1]) / 2)
      if (!target) continue
      const [prt, color] = target
      prt.add([P[i][j], P[i + 1][j], P[i + 1][j2]], [N[i][j], N[i + 1][j], N[i + 1][j2]], color)
      prt.add([P[i][j], P[i + 1][j2], P[i][j2]], [N[i][j], N[i + 1][j2], N[i][j2]], color)
    }
  return P
}

// Flat cap closing the end of a loft.
function cap(prt, ring, x, dir, color) {
  const cy = 0,
    cz = ring.reduce((s, p) => s + p[1], 0) / ring.length
  for (let j = 0; j < ring.length; j++) {
    const a = ring[j],
      b = ring[(j + 1) % ring.length]
    prt.tri([x, cy, cz], [x, a[0], a[1]], [x, b[0], b[1]], color, [dir, 0, 0])
  }
}

// Outline of the body seen from above at height z, for the left half: from the middle of the
// front, along the front, down the side and across the back to the middle of the rear. Returns
// a function giving the point and outward direction at a distance s along it.
function outline(body, xs, z) {
  const pts = [[xs.at(-1), 0]]
  for (let i = xs.length - 1; i >= 0; i--) pts.push([xs[i], halfWidth(body(xs[i]), z)])
  pts.push([xs[0], 0])
  const len = [0]
  for (let i = 1; i < pts.length; i++)
    len.push(len[i - 1] + Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]))
  const total = len.at(-1)
  const at = (s) => {
    s = Math.min(total, Math.max(0, s))
    let i = 1
    while (i < pts.length - 1 && len[i] < s) i++
    const a = pts[i - 1],
      b = pts[i]
    const seg = len[i] - len[i - 1] || 1
    const t = (s - len[i - 1]) / seg
    const tx = (b[0] - a[0]) / seg,
      ty = (b[1] - a[1]) / seg
    // outward is to the right of the walking direction (front to back on the left side)
    return { p: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], n: [ty, -tx] }
  }
  return { at, total }
}

// A band painted on the body, between heights z0 and z1 and between distances s0 and s1 along
// the outline (from the front middle; negative values count from the rear middle). Drawn on
// both sides, slightly off the surface. Used for lamps, grilles, plates and black trim.
function band(prt, body, xs, { z: [z0, z1], s: [s0, s1], lift = 0.012, color, side = 0 }) {
  const lo = outline(body, xs, z0),
    hi = outline(body, xs, z1)
  // from the rear: -1.0 to -0.3 means 1.0 m to 0.3 m before the rear middle
  const range = (o) => (s0 < 0 ? [o.total + s0, o.total + s1] : [s0, Math.min(s1, o.total)])
  const STEP = 0.04
  const n = Math.max(1, Math.ceil(Math.abs(s1 - s0) / STEP))
  const sides = side ? [side] : [1, -1]
  for (const sy of sides)
    for (let i = 0; i < n; i++) {
      const pt = (o, k, z) => {
        const [a, b] = range(o)
        const { p, n: nn } = o.at(a + ((b - a) * k) / n)
        return {
          v: [p[0] + nn[0] * lift, sy * (p[1] + nn[1] * lift), z],
          n: [nn[0], sy * nn[1], 0],
        }
      }
      const A = pt(lo, i, z0),
        B = pt(lo, i + 1, z0),
        C = pt(hi, i + 1, z1),
        D = pt(hi, i, z1)
      prt.add([A.v, B.v, C.v], [A.n, B.n, C.n], color)
      prt.add([A.v, C.v, D.v], [A.n, C.n, D.n], color)
    }
}

// Tyre and rim. The tyre's outer face is at |y| = outer.
function wheel(matte, shiny, x, side, r, width, outer) {
  const SEG = 28
  const yo = side * outer,
    yi = side * (outer - width)
  const lerpY = (t) => yi + (yo - yi) * t
  // tyre cross section: (radius, position across the tread 0..1)
  const prof = [
    [r * 0.66, 0],
    [r - 0.035, 0],
    [r, 0.12],
    [r, 0.88],
    [r - 0.035, 1],
    [r * 0.66, 1],
  ]
  const P = (rad, t, a) => [x + rad * Math.cos(a), lerpY(t), r + rad * Math.sin(a)]
  for (let k = 0; k < SEG; k++) {
    const a0 = (k / SEG) * Math.PI * 2,
      a1 = ((k + 1) / SEG) * Math.PI * 2
    for (let j = 0; j < prof.length - 1; j++) {
      const [r0, t0] = prof[j],
        [r1, t1] = prof[j + 1]
      const am = (a0 + a1) / 2
      const out = [Math.cos(am) * (r1 - r0 === 0 ? 1 : 0.3), side * (t1 + t0 - 1), Math.sin(am)]
      matte.quad(P(r0, t0, a0), P(r0, t0, a1), P(r1, t1, a1), P(r1, t1, a0), RUBBER, out)
    }
  }
  // rim: dark dish set back, a bright lip, five spokes and a hub
  const face = [0, side, 0]
  const disc = (rad0, rad1, y, color, prt, seg = SEG) => {
    for (let k = 0; k < seg; k++) {
      const a0 = (k / seg) * Math.PI * 2,
        a1 = ((k + 1) / seg) * Math.PI * 2
      const p = (rad, a) => [x + rad * Math.cos(a), y, r + rad * Math.sin(a)]
      prt.quad(p(rad0, a0), p(rad0, a1), p(rad1, a1), p(rad1, a0), color, face)
    }
  }
  disc(0, r * 0.66, yo - side * 0.04, RIM_DARK, matte)
  disc(r * 0.58, r * 0.66, yo - side * 0.008, RIM, shiny)
  for (let k = 0; k < 5; k++) {
    const a = (k / 5) * Math.PI * 2 + 0.3
    const w0 = 0.11,
      w1 = 0.06
    const p = (rad, da) => [
      x + rad * Math.cos(a + da),
      yo - side * 0.014,
      r + rad * Math.sin(a + da),
    ]
    shiny.quad(p(r * 0.14, -w0), p(r * 0.14, w0), p(r * 0.6, w1), p(r * 0.6, -w1), RIM, face)
  }
  disc(0, r * 0.15, yo - side * 0.01, RIM, shiny, 12)
}

// Dark wheel arch on the body side around a wheel, following the curve of the panel.
function arch(matte, body, x, side, r) {
  const R = r + 0.07
  const SEG = 18
  const onBody = (px, pz) => {
    const k = body(px)
    const z = Math.max(pz, k.zb + 0.01)
    return [px, side * (halfWidth(k, z) + 0.01), z]
  }
  const c = onBody(x, r)
  for (let k = 0; k < SEG; k++) {
    const a0 = -0.15 + ((Math.PI + 0.3) * k) / SEG,
      a1 = -0.15 + ((Math.PI + 0.3) * (k + 1)) / SEG
    const A = onBody(x + R * Math.cos(a0), r + R * Math.sin(a0)),
      B = onBody(x + R * Math.cos(a1), r + R * Math.sin(a1))
    matte.tri(c, A, B, ARCH, [0, side, 0])
  }
}

function buildModel(spec) {
  const paint = part(),
    shiny = part(),
    matte = part()
  const lamps = {
    head: part(),
    tail: part(),
    brake: part(),
    indicatorLeft: part(),
    indicatorRight: part(),
  }
  const body = bodyAt(spec)
  const xf = spec.body.at(-1).x,
    xr = spec.body[0].x
  // stations closer together near the ends, where the shape changes fastest
  const N = 46
  const xs = Array.from(
    { length: N + 1 },
    (_, i) => xr + ((xf - xr) * (1 - Math.cos((Math.PI * i) / N))) / 2,
  )

  // lower body
  const rings = xs.map((x) => fullRing(bodyHalfRing(body(x))))
  const zc = (body(0).zb + body(0).zt) / 2
  loft(xs, rings, zc, () => [paint, WHITE])
  cap(paint, rings[0], xr, -1, WHITE)
  cap(paint, rings.at(-1), xf, 1, WHITE)

  // cabin: sits on the waist of the body; side glass, painted roof and pillars
  const ck = spec.cabin
  const top = linearTrack(ck, 'top'),
    wTop = linearTrack(ck, 'w')
  const cx0 = ck[0].x,
    cx1 = ck.at(-1).x
  const M = 34
  const cxs = Array.from({ length: M + 1 }, (_, i) => cx0 + ((cx1 - cx0) * i) / M)
  // half ring of the cabin: [y, z, kind]
  const cabinHalf = (x) => {
    const k = body(x)
    const zb = k.zt - 0.015,
      wb = k.wt - 0.01
    const zt = Math.max(top(x), zb + 0.002)
    const h = zt - zb
    const wt = Math.min(wTop(x), wb)
    const rr = Math.min(0.06, h * 0.4)
    const side = (t) => [wb + (wt + 0.02 - wb) * t, zb + (h - rr) * t]
    return [
      [0, zb, 'base'],
      [wb, zb, 'side'],
      [...side(0.35), 'side'],
      [...side(0.7), 'side'],
      [...side(1), 'edge'],
      [wt, zt - rr * 0.3, 'edge'],
      [wt - rr * 0.7, zt, 'top'],
      [wt * 0.5, zt + 0.012, 'top'],
      [0, zt + 0.016, 'top'],
    ]
  }
  const inside = (x, ranges) => (ranges ?? []).some(([a, b]) => x >= a && x <= b)
  const cabinRings = cxs.map((x) => fullRing(cabinHalf(x).map(([y, z]) => [y, z])))
  const kinds = fullRing(cabinHalf(0).map(([, , kd], i) => [i, kd])).map(([, kd]) => kd)
  loft(cxs, cabinRings, body(0).zt, (i, j, x) => {
    const kind = kinds[j],
      next = kinds[(j + 1) % kinds.length]
    if (kind === 'base' || next === 'base') return null // underside, inside the body
    const isTop = kind === 'top' || next === 'top'
    const isSide = (kind === 'side' || next === 'side') && !isTop
    if (isTop && !(kind === 'edge' || next === 'edge'))
      return inside(x, [spec.roof]) ? [paint, WHITE] : [shiny, GLASS]
    if (isSide) return inside(x, spec.pillars) ? [paint, WHITE] : [shiny, GLASS]
    return [paint, WHITE] // roof edge and A pillars
  })

  // pickup bed: a dark liner inside the rails
  if (spec.bed) {
    const [b0, b1] = spec.bed
    const STEP = 0.1
    for (let x = b0; x < b1 - 1e-6; x += STEP) {
      const xa = x,
        xb = Math.min(b1, x + STEP)
      const ka = body(xa),
        kb = body(xb)
      const za = ka.zt + 0.045,
        zb = kb.zt + 0.045
      matte.quad(
        [xa, -(ka.wt - 0.05), za],
        [xb, -(kb.wt - 0.05), zb],
        [xb, kb.wt - 0.05, zb],
        [xa, ka.wt - 0.05, za],
        BED,
        [0, 0, 1],
      )
    }
  }

  // mirrors on the doors, just behind the windscreen
  for (const sy of [1, -1]) {
    const mx = spec.mirror[0],
      mz = spec.mirror[1]
    const k = body(mx)
    const y0 = k.wt - 0.02,
      y1 = k.hw + 0.1
    const box = (x0, x1, ya, yb, z0, z1, color, prt) => {
      const c = [
        [x0, ya, z0],
        [x1, ya, z0],
        [x1, yb, z0],
        [x0, yb, z0],
        [x0, ya, z1],
        [x1, ya, z1],
        [x1, yb, z1],
        [x0, yb, z1],
      ].map(([px, py, pz]) => [px, sy * py, pz])
      const mid = [(x0 + x1) / 2, (sy * (ya + yb)) / 2, (z0 + z1) / 2]
      const q = (a, b, cc, d) => {
        const o = [
          (c[a][0] + c[cc][0]) / 2 - mid[0],
          (c[a][1] + c[cc][1]) / 2 - mid[1],
          (c[a][2] + c[cc][2]) / 2 - mid[2],
        ]
        prt.quad(c[a], c[b], c[cc], c[d], color, o)
      }
      q(0, 1, 2, 3)
      q(4, 5, 6, 7)
      q(0, 1, 5, 4)
      q(1, 2, 6, 5)
      q(2, 3, 7, 6)
      q(3, 0, 4, 7)
    }
    box(mx - 0.08, mx + 0.05, y0, y1, mz, mz + 0.11, WHITE, paint)
    box(mx - 0.08, mx - 0.06, y0 + 0.06, y1 - 0.01, mz + 0.01, mz + 0.1, PLASTIC, matte)
    if (spec.rails) {
      // roof rails along the edges of the roof
      const [r0, r1] = [spec.roof[0] + 0.12, spec.roof[1] - 0.12]
      const ry = wTop((r0 + r1) / 2) - 0.1
      const rz = Math.max(top(r0), top(r1)) + 0.01
      box(r0, r1, ry - 0.025, ry + 0.025, rz, rz + 0.05, RAIL, matte)
      for (const fx of [r0, r1 - 0.12])
        box(fx, fx + 0.12, ry - 0.035, ry + 0.035, rz - 0.02, rz + 0.06, RAIL, matte)
    }
  }

  // wheels and arches
  for (const wx of spec.wheels)
    for (const sy of [1, -1]) {
      const k = body(wx)
      const outer = halfWidth(k, spec.r) - 0.005
      arch(matte, body, wx, sy, spec.r)
      wheel(matte, shiny, wx, sy, spec.r, spec.tyre, Math.max(outer, k.hw - 0.03))
    }

  // spare wheel on the tailgate (Defender): built like a road wheel, then turned to face back
  if (spec.spare) {
    const { z, y = 0 } = spec.spare
    const tm = part(),
      ts = part()
    wheel(tm, ts, 0, 1, spec.r, spec.tyre, spec.tyre)
    for (const [from, to] of [
      [tm, matte],
      [ts, shiny],
    ]) {
      const P = from.positions,
        Nn = from.normals
      for (let i = 0; i < P.length; i += 3) {
        to.positions.push(xr - 0.02 - P[i + 1], y + P[i], z + P[i + 2] - spec.r)
        to.normals.push(-Nn[i + 1], Nn[i], Nn[i + 2])
      }
      to.colors.push(...from.colors)
    }
  }

  // painted details: lamps, grille, plates, black trim
  for (const b of spec.details ?? []) {
    const prt = b.lamp ? lamps[b.lamp] : b.color === PLATE ? shiny : matte
    band(prt, body, xs, { ...b, color: b.lamp ? WHITE : b.color, side: b.side ?? 0 })
    // the lamp glass shows even when the lamp is off
    if (b.lamp === 'head' || b.lamp === 'tail')
      band(shiny, body, xs, {
        ...b,
        lift: 0.006,
        color: b.lamp === 'head' ? LAMP_FRONT : LAMP_REAR,
      })
  }

  // Lean the nose and the tail back towards the top, so the bumpers stick out further than the
  // bonnet and boot edges, like on real cars. Moves every point near the ends (the wheels are
  // further in, so they don't move).
  const ends = [
    { from: xf - 0.5, to: xf, k: body(xf), rake: -(spec.rake?.[0] ?? 0.12) },
    { from: xr + 0.5, to: xr, k: body(xr), rake: spec.rake?.[1] ?? 0.08 },
  ]
  for (const prt of [paint, shiny, matte, ...Object.values(lamps)]) {
    const P = prt.positions
    for (let i = 0; i < P.length; i += 3)
      for (const e of ends) {
        const t = clamp01((P[i] - e.from) / (e.to - e.from))
        if (t <= 0) continue
        const h = clamp01((P[i + 2] - e.k.zb) / (e.k.zt + 0.1 - e.k.zb))
        P[i] += e.rake * t * t * (3 - 2 * t) * h
      }
  }

  return {
    name: spec.name,
    length: xf - xr,
    paint: paint.done(),
    shiny: shiny.done(),
    matte: matte.done(),
    ...Object.fromEntries(Object.entries(lamps).map(([k, p]) => [k, p.done()])),
  }
}

// ---------------------------------------------------------------------------------------------
// The models. body keys run from the rear bumper (first) to the front bumper (last); cabin keys
// give the glass line from the bottom of the rear window to the bottom of the windscreen.
// details: { z: [bottom, top], s: [from, to] along the outline from the front middle (negative
// from the rear middle), lamp or color }

// Mid-size sedan (Camry, Sonata, Accord): 4.88 x 1.84 x 1.45 m, 2.82 m wheelbase
const SEDAN = {
  name: 'sedan',
  rake: [0.2, 0.12],
  body: [
    { x: -2.44, hw: 0.66, wt: 0.52, zb: 0.44, zs: 0.64, zt: 0.86 },
    { x: -2.38, hw: 0.82, zb: 0.38, zs: 0.66, zt: 0.93 },
    { x: -2.2, hw: 0.885, zb: 0.33, zs: 0.68, zt: 0.97 },
    { x: -1.8, hw: 0.91, zb: 0.29, zs: 0.69, zt: 1.01 },
    { x: -1.2, hw: 0.92, zb: 0.27, zs: 0.68, zt: 0.99 },
    { x: 0.0, hw: 0.92, zb: 0.26, zs: 0.66, zt: 0.96 },
    { x: 1.05, hw: 0.92, zb: 0.26, zs: 0.63, zt: 0.91 },
    { x: 1.7, hw: 0.915, zb: 0.26, zs: 0.6, zt: 0.82 },
    { x: 2.2, hw: 0.895, zb: 0.27, zs: 0.56, zt: 0.75 },
    { x: 2.38, hw: 0.83, zb: 0.3, zs: 0.53, zt: 0.69 },
    { x: 2.44, hw: 0.64, wt: 0.5, zb: 0.36, zs: 0.52, zt: 0.63 },
  ],
  cabin: [
    { x: -1.84, top: 1.01, w: 0.7 },
    { x: -0.98, top: 1.43, w: 0.6 },
    { x: -0.5, top: 1.455, w: 0.62 },
    { x: 0.1, top: 1.43, w: 0.62 },
    { x: 1.02, top: 0.9, w: 0.74 },
  ],
  roof: [-0.97, 0.12],
  pillars: [
    [-0.33, -0.22],
    [-1.9, -1.28],
  ],
  wheels: [-1.4, 1.42],
  r: 0.33,
  tyre: 0.22,
  mirror: [0.82, 0.92],
  details: [
    { z: [0.6, 0.72], s: [0.32, 0.98], lamp: 'head' },
    { z: [0.55, 0.6], s: [0.82, 1.02], lamp: 'indicatorLeft', side: 1 },
    { z: [0.55, 0.6], s: [0.82, 1.02], lamp: 'indicatorRight', side: -1 },
    { z: [0.3, 0.5], s: [0, 0.48], color: GRILLE },
    { z: [0.36, 0.48], s: [0, 0.26], color: PLATE, lift: 0.02 },
    { z: [0.8, 0.9], s: [-1.0, -0.3], lamp: 'tail' },
    { z: [0.8, 0.9], s: [-1.0, -0.3], lamp: 'brake', lift: 0.018 },
    { z: [0.74, 0.79], s: [-0.95, -0.7], lamp: 'indicatorLeft', side: 1 },
    { z: [0.74, 0.79], s: [-0.95, -0.7], lamp: 'indicatorRight', side: -1 },
    { z: [0.58, 0.71], s: [-0.26, 0], color: PLATE, lift: 0.02 },
    { z: [0.36, 0.46], s: [-0.8, 0], color: PLASTIC },
  ],
}

// Full-size SUV (Land Cruiser, Tahoe, Patrol): 4.98 x 1.98 x 1.92 m, 2.85 m wheelbase
const SUV = {
  name: 'suv',
  rake: [0.1, 0.05],
  body: [
    { x: -2.49, hw: 0.84, wt: 0.74, zb: 0.56, zs: 0.86, zt: 1.12 },
    { x: -2.42, hw: 0.95, zb: 0.5, zs: 0.88, zt: 1.17 },
    { x: -2.1, hw: 0.99, zb: 0.45, zs: 0.88, zt: 1.18 },
    { x: 0.0, hw: 0.99, zb: 0.42, zs: 0.86, zt: 1.16 },
    { x: 1.2, hw: 0.99, zb: 0.42, zs: 0.84, zt: 1.14 },
    { x: 2.15, hw: 0.98, zb: 0.43, zs: 0.82, zt: 1.09 },
    { x: 2.42, hw: 0.93, zb: 0.46, zs: 0.8, zt: 1.03 },
    { x: 2.49, hw: 0.76, wt: 0.66, zb: 0.52, zs: 0.78, zt: 0.94 },
  ],
  cabin: [
    { x: -2.47, top: 1.16, w: 0.84 },
    { x: -2.38, top: 1.86, w: 0.8 },
    { x: -1.2, top: 1.9, w: 0.81 },
    { x: 0.45, top: 1.88, w: 0.81 },
    { x: 1.22, top: 1.14, w: 0.86 },
  ],
  roof: [-2.34, 0.46],
  rails: true,
  pillars: [
    [-0.12, 0.0],
    [-1.3, -1.18],
    [-2.6, -2.08],
  ],
  wheels: [-1.4, 1.45],
  r: 0.39,
  tyre: 0.27,
  mirror: [1.0, 1.14],
  details: [
    { z: [0.84, 0.97], s: [0.4, 1.12], lamp: 'head' },
    { z: [0.78, 0.83], s: [0.9, 1.15], lamp: 'indicatorLeft', side: 1 },
    { z: [0.78, 0.83], s: [0.9, 1.15], lamp: 'indicatorRight', side: -1 },
    { z: [0.6, 0.95], s: [0, 0.42], color: GRILLE },
    { z: [0.47, 0.6], s: [0, 0.28], color: PLATE, lift: 0.02 },
    { z: [0.98, 1.12], s: [-1.12, -0.62], lamp: 'tail' },
    { z: [0.98, 1.12], s: [-1.12, -0.62], lamp: 'brake', lift: 0.018 },
    { z: [0.92, 0.97], s: [-1.08, -0.8], lamp: 'indicatorLeft', side: 1 },
    { z: [0.92, 0.97], s: [-1.08, -0.8], lamp: 'indicatorRight', side: -1 },
    { z: [0.74, 0.87], s: [-0.27, 0], color: PLATE, lift: 0.02 },
    { z: [0.47, 0.6], s: [0, 7], color: PLASTIC, lift: 0.008 },
  ],
}

// Compact crossover (RAV4, Tucson, CX-5): 4.60 x 1.86 x 1.69 m, 2.69 m wheelbase
const CROSSOVER = {
  name: 'crossover',
  rake: [0.16, 0.1],
  body: [
    { x: -2.3, hw: 0.78, wt: 0.66, zb: 0.48, zs: 0.78, zt: 1.0 },
    { x: -2.2, hw: 0.9, zb: 0.43, zs: 0.8, zt: 1.06 },
    { x: -1.6, hw: 0.93, zb: 0.37, zs: 0.8, zt: 1.07 },
    { x: 0.0, hw: 0.93, zb: 0.35, zs: 0.77, zt: 1.03 },
    { x: 1.1, hw: 0.93, zb: 0.34, zs: 0.74, zt: 1.0 },
    { x: 2.0, hw: 0.92, zb: 0.35, zs: 0.7, zt: 0.92 },
    { x: 2.24, hw: 0.87, zb: 0.37, zs: 0.66, zt: 0.86 },
    { x: 2.3, hw: 0.7, wt: 0.58, zb: 0.42, zs: 0.62, zt: 0.78 },
  ],
  cabin: [
    { x: -2.2, top: 1.06, w: 0.76 },
    { x: -1.82, top: 1.56, w: 0.68 },
    { x: -1.0, top: 1.65, w: 0.71 },
    { x: -0.2, top: 1.68, w: 0.72 },
    { x: 0.42, top: 1.62, w: 0.72 },
    { x: 1.12, top: 1.0, w: 0.78 },
  ],
  roof: [-1.78, 0.38],
  rails: true,
  pillars: [
    [-0.22, -0.11],
    [-2.3, -1.5],
  ],
  wheels: [-1.3, 1.39],
  r: 0.36,
  tyre: 0.24,
  mirror: [0.95, 1.02],
  details: [
    { z: [0.7, 0.8], s: [0.36, 1.06], lamp: 'head' },
    { z: [0.65, 0.7], s: [0.88, 1.08], lamp: 'indicatorLeft', side: 1 },
    { z: [0.65, 0.7], s: [0.88, 1.08], lamp: 'indicatorRight', side: -1 },
    { z: [0.5, 0.68], s: [0, 0.4], color: GRILLE },
    { z: [0.42, 0.54], s: [0, 0.26], color: PLATE, lift: 0.02 },
    { z: [0.9, 1.0], s: [-1.06, -0.38], lamp: 'tail' },
    { z: [0.9, 1.0], s: [-1.06, -0.38], lamp: 'brake', lift: 0.018 },
    { z: [0.84, 0.89], s: [-1.0, -0.75], lamp: 'indicatorLeft', side: 1 },
    { z: [0.84, 0.89], s: [-1.0, -0.75], lamp: 'indicatorRight', side: -1 },
    { z: [0.66, 0.79], s: [-0.26, 0], color: PLATE, lift: 0.02 },
    { z: [0.38, 0.52], s: [0, 7], color: PLASTIC, lift: 0.008 },
  ],
}

// Full-size crew-cab pickup (GMC Sierra, Silverado): 5.89 x 2.06 x 1.95 m, 3.74 m wheelbase.
// Tall flat bonnet, big grille, square body, short bed.
const PICKUP = {
  name: 'pickup',
  rake: [0.06, 0.02],
  boxy: 4,
  tuck: 0.08,
  body: [
    { x: -2.945, hw: 0.98, wt: 0.92, zb: 0.66, zs: 0.98, zt: 1.22 },
    { x: -2.86, hw: 1.02, zb: 0.6, zs: 1.0, zt: 1.27 },
    { x: 0.0, hw: 1.03, zb: 0.55, zs: 1.0, zt: 1.3 },
    { x: 2.0, hw: 1.03, zb: 0.55, zs: 0.98, zt: 1.3 },
    { x: 2.8, hw: 1.02, zb: 0.58, zs: 0.96, zt: 1.26 },
    { x: 2.945, hw: 0.92, wt: 0.86, zb: 0.64, zs: 0.92, zt: 1.18 },
  ],
  cabin: [
    { x: -0.62, top: 1.3, w: 0.95 },
    { x: -0.55, top: 1.93, w: 0.9 },
    { x: 0.9, top: 1.95, w: 0.9 },
    { x: 1.62, top: 1.3, w: 0.96 },
  ],
  roof: [-0.55, 0.95],
  pillars: [[0.2, 0.32]],
  bed: [-2.85, -0.68],
  wheels: [-1.74, 2.0],
  r: 0.41,
  tyre: 0.28,
  mirror: [1.35, 1.36],
  details: [
    { z: [1.06, 1.2], s: [0.56, 1.14], lamp: 'head' },
    { z: [0.99, 1.04], s: [0.9, 1.16], lamp: 'indicatorLeft', side: 1 },
    { z: [0.99, 1.04], s: [0.9, 1.16], lamp: 'indicatorRight', side: -1 },
    { z: [0.76, 1.2], s: [0, 0.56], color: GRILLE },
    { z: [0.62, 0.75], s: [0, 0.27], color: PLATE, lift: 0.02 },
    { z: [0.95, 1.25], s: [-1.06, -0.9], lamp: 'tail' },
    { z: [0.95, 1.25], s: [-1.06, -0.9], lamp: 'brake', lift: 0.018 },
    { z: [0.88, 0.94], s: [-1.06, -0.9], lamp: 'indicatorLeft', side: 1 },
    { z: [0.88, 0.94], s: [-1.06, -0.9], lamp: 'indicatorRight', side: -1 },
    { z: [0.74, 0.87], s: [-0.27, 0], color: PLATE, lift: 0.02 },
    { z: [0.6, 0.74], s: [0, 8], color: PLASTIC, lift: 0.008 },
  ],
}

// Boxy off-roader (Land Rover Defender 110): 4.76 x 2.00 x 1.97 m body, 3.02 m wheelbase, short
// overhangs, flat sides, upright windscreen, wide flat roof and a spare wheel on the tailgate.
const DEFENDER = {
  name: 'defender',
  rake: [0.04, 0],
  boxy: 4.5,
  tuck: 0.07,
  body: [
    { x: -2.38, hw: 0.9, wt: 0.84, zb: 0.62, zs: 0.9, zt: 1.12 },
    { x: -2.31, hw: 0.98, zb: 0.55, zs: 0.9, zt: 1.17 },
    { x: 0.0, hw: 0.99, zb: 0.5, zs: 0.88, zt: 1.17 },
    { x: 1.9, hw: 0.99, zb: 0.5, zs: 0.86, zt: 1.15 },
    { x: 2.3, hw: 0.97, zb: 0.52, zs: 0.84, zt: 1.12 },
    { x: 2.38, hw: 0.86, wt: 0.8, zb: 0.58, zs: 0.82, zt: 1.06 },
  ],
  cabin: [
    { x: -2.34, top: 1.17, w: 0.93 },
    { x: -2.3, top: 1.95, w: 0.9 },
    { x: 0.86, top: 1.97, w: 0.9 },
    { x: 1.26, top: 1.17, w: 0.93 },
  ],
  roof: [-2.28, 0.86],
  pillars: [
    [-0.1, 0.02],
    [-1.26, -1.14],
    [-2.5, -1.75],
  ],
  wheels: [-1.44, 1.58],
  r: 0.4,
  tyre: 0.27,
  spare: { z: 1.02, y: 0.12 },
  mirror: [1.12, 1.2],
  details: [
    { z: [0.92, 1.04], s: [0.48, 0.84], lamp: 'head' },
    { z: [0.86, 0.91], s: [0.62, 0.84], lamp: 'indicatorLeft', side: 1 },
    { z: [0.86, 0.91], s: [0.62, 0.84], lamp: 'indicatorRight', side: -1 },
    { z: [0.84, 1.02], s: [0, 0.46], color: GRILLE },
    { z: [0.62, 0.74], s: [0, 0.27], color: PLATE, lift: 0.02 },
    { z: [0.86, 1.16], s: [-1.04, -0.9], lamp: 'tail' },
    { z: [0.86, 1.16], s: [-1.04, -0.9], lamp: 'brake', lift: 0.018 },
    { z: [0.8, 0.85], s: [-1.04, -0.9], lamp: 'indicatorLeft', side: 1 },
    { z: [0.8, 0.85], s: [-1.04, -0.9], lamp: 'indicatorRight', side: -1 },
    { z: [0.68, 0.81], s: [-0.66, -0.4], color: PLATE, lift: 0.02 },
    { z: [0.5, 0.66], s: [0, 8], color: PLASTIC, lift: 0.008 },
  ],
}

export const CAR_MODELS = [SEDAN, SUV, CROSSOVER, PICKUP, DEFENDER].map(buildModel)

// How common each model is, roughly as on Riyadh's main roads.
export const MODEL_SHARE = { sedan: 36, suv: 20, crossover: 20, pickup: 14, defender: 10 }

// Car colours and how often they appear: mostly white, silver and grey, then black and beige.
export const PAINT_SHARE = [
  { color: [236, 237, 234], share: 36 }, // white
  { color: [186, 190, 194], share: 15 }, // silver
  { color: [122, 126, 132], share: 10 }, // metallic grey
  { color: [30, 31, 34], share: 13 }, // black
  { color: [72, 75, 80], share: 9 }, // dark grey
  { color: [198, 184, 156], share: 10 }, // beige / champagne
  { color: [36, 50, 84], share: 5 }, // dark blue
  { color: [94, 26, 30], share: 2 }, // dark red
]
