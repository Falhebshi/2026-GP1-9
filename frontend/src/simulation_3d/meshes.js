// Small 3D models built in code (no model files): palm trunk and crown, shrub, tree crown and
// street light. Sizes are in metres, z is up. Each model carries its own colours per vertex, so
// the layers draw them with getColor white.

function builder() {
  const positions = [],
    normals = [],
    colors = []
  // triangle with one colour; the normal is turned to face `out` (a direction), if given
  const tri = (a, b, c, color, out) => {
    const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]],
      v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]]
    let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    const len = Math.hypot(...n) || 1
    n = n.map((x) => x / len)
    if (out && n[0] * out[0] + n[1] * out[1] + n[2] * out[2] < 0) n = n.map((x) => -x)
    positions.push(...a, ...b, ...c)
    for (let i = 0; i < 3; i++) {
      normals.push(...n)
      colors.push(...color)
    }
  }
  const done = () => ({
    positions: { size: 3, value: new Float32Array(positions) },
    normals: { size: 3, value: new Float32Array(normals) },
    colors: { size: 3, value: new Float32Array(colors) },
  })
  return { tri, done }
}

const rgb = (r, g, b) => [r / 255, g / 255, b / 255]
const mix = (a, b, t) => a.map((v, i) => v + (b[i] - v) * t)

// fixed pseudo random numbers, so models are the same on every load
function seeded(seed) {
  let s = seed >>> 0
  return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296
}

// Tapered tube from z0 to z1. color(z) gives the colour along the height.
function tube(m, r0, r1, z0, z1, sides, rings, color, x = 0, y = 0) {
  for (let k = 0; k < rings; k++) {
    const za = z0 + ((z1 - z0) * k) / rings,
      zb = z0 + ((z1 - z0) * (k + 1)) / rings
    const ra = r0 + ((r1 - r0) * k) / rings,
      rb = r0 + ((r1 - r0) * (k + 1)) / rings
    const c = color((za + zb) / 2)
    for (let i = 0; i < sides; i++) {
      const a0 = (i / sides) * Math.PI * 2,
        a1 = ((i + 1) / sides) * Math.PI * 2
      const p = (r, a, z) => [x + r * Math.cos(a), y + r * Math.sin(a), z]
      const out = [Math.cos((a0 + a1) / 2), Math.sin((a0 + a1) / 2), 0]
      m.tri(p(ra, a0, za), p(ra, a1, za), p(rb, a1, zb), c, out)
      m.tri(p(ra, a0, za), p(rb, a1, zb), p(rb, a0, zb), c, out)
    }
  }
}

// Date palm trunk, 1 m tall (scaled to the palm's height): slightly wider at the base, with the
// rough rings left by old leaf bases shown as alternating bands.
export const PALM_TRUNK = (() => {
  const m = builder()
  const light = rgb(146, 120, 92),
    dark = rgb(118, 96, 74)
  tube(m, 0.026, 0.02, 0, 1, 10, 24, (z) => (Math.floor(z * 24) % 2 ? light : dark))
  return m.done()
})()

// Date palm crown: two tiers of long arching fronds folded along the mid-rib, dark green near the
// trunk and lighter at the tips, the lower tier a little drier.
export const PALM_CROWN = (() => {
  const m = builder()
  const random = seeded(3)
  const tiers = [
    { count: 11, lift: 1.0, droop: 2.2, len: 3.3, base: rgb(64, 92, 46), tip: rgb(118, 144, 72) },
    { count: 9, lift: 0.4, droop: 2.8, len: 3.0, base: rgb(84, 100, 52), tip: rgb(150, 150, 84) },
  ]
  tiers.forEach((tier, ti) => {
    for (let f = 0; f < tier.count; f++) {
      const a = (f / tier.count) * Math.PI * 2 + ti * 0.3 + (random() - 0.5) * 0.2
      const len = tier.len * (0.9 + random() * 0.2)
      const ca = Math.cos(a),
        sa = Math.sin(a)
      const STEPS = 10
      const at = (t, side) => {
        const r = t * len
        const z = tier.lift * t * 1.6 - tier.droop * t * t
        const w = 0.38 * Math.sin(Math.PI * Math.min(1, t * 1.1)) * side
        const fold = Math.abs(side) * 0.08 * Math.sin(Math.PI * t) // leaflets lift towards the edges
        return [r * ca - w * sa, r * sa + w * ca, z + fold]
      }
      for (let i = 0; i < STEPS; i++) {
        const t0 = i / STEPS,
          t1 = (i + 1) / STEPS
        const c = mix(tier.base, tier.tip, (t0 + t1) / 2)
        const rib0 = at(t0, 0),
          rib1 = at(t1, 0)
        for (const side of [-1, 1]) {
          const e0 = at(t0, side),
            e1 = at(t1, side)
          m.tri(rib0, e0, e1, c, [0, 0, 1])
          m.tri(rib0, e1, rib1, c, [0, 0, 1])
        }
      }
    }
  })
  return m.done()
})()

// Rough ball made of a few overlapping, slightly lumpy lobes, so foliage doesn't look like a
// smooth sphere. Radius about 1 m.
function foliage(seed, lobes, palette) {
  const m = builder()
  const random = seeded(seed)
  const NLAT = 7,
    NLON = 10
  for (let l = 0; l < lobes; l++) {
    const cx = l === 0 ? 0 : (random() - 0.5) * 0.9,
      cy = l === 0 ? 0 : (random() - 0.5) * 0.9,
      cz = l === 0 ? 0 : (random() - 0.3) * 0.5
    const r = l === 0 ? 0.75 : 0.45 + random() * 0.25
    const color = palette[Math.floor(random() * palette.length)]
    const bump = Array.from({ length: (NLAT + 1) * (NLON + 1) }, () => 0.88 + random() * 0.24)
    const pt = (i, j) => {
      const th = (i / NLAT) * Math.PI,
        ph = (j / NLON) * Math.PI * 2
      const k = bump[i * (NLON + 1) + (j % NLON)] * r
      return [
        cx + k * Math.sin(th) * Math.cos(ph),
        cy + k * Math.sin(th) * Math.sin(ph),
        cz + k * Math.cos(th),
      ]
    }
    for (let i = 0; i < NLAT; i++)
      for (let j = 0; j < NLON; j++) {
        const a = pt(i, j),
          b = pt(i + 1, j),
          c = pt(i + 1, j + 1),
          d = pt(i, j + 1)
        const col = color
        const out = [a[0] - cx, a[1] - cy, a[2] - cz]
        m.tri(a, b, c, col, out)
        m.tri(a, c, d, col, out)
      }
  }
  return m.done()
}

export const SHRUB = foliage(11, 4, [rgb(88, 112, 64), rgb(76, 100, 58), rgb(102, 120, 70)])
export const TREE_CROWN = foliage(23, 7, [rgb(86, 118, 66), rgb(72, 104, 58), rgb(104, 130, 76)])

export const TREE_TRUNK = (() => {
  const m = builder()
  tube(m, 0.16, 0.1, 0, 1, 8, 2, () => rgb(112, 94, 76))
  return m.done()
})()

// Street light: slim tapered pole 10 m tall with one arm reaching 1.8 m over the road (+x) and a
// flat luminaire at the end. The light opening under the luminaire is a separate model so it can
// glow at night.
export const LAMP_POLE = (() => {
  const m = builder()
  const metal = rgb(150, 154, 158)
  tube(m, 0.1, 0.065, 0, 9.7, 10, 4, () => metal)
  // arm: a thin box rising slightly towards the road
  const box = (x0, x1, z0, z1, w, h, c) => {
    const p = (x, s, t) => [x, s * w, (x === x0 ? z0 : z1) + t * h]
    const corners = [
      [p(x0, -1, 0), p(x1, -1, 0), p(x1, 1, 0), p(x0, 1, 0)],
      [p(x0, -1, 1), p(x1, -1, 1), p(x1, 1, 1), p(x0, 1, 1)],
    ]
    const [b, t] = corners
    const quad = (a, bb, cc, d, out) => {
      m.tri(a, bb, cc, c, out)
      m.tri(a, cc, d, c, out)
    }
    quad(b[0], b[1], b[2], b[3], [0, 0, -1])
    quad(t[0], t[1], t[2], t[3], [0, 0, 1])
    quad(b[0], b[1], t[1], t[0], [0, -1, 0])
    quad(b[3], b[2], t[2], t[3], [0, 1, 0])
    quad(b[0], b[3], t[3], t[0], [-1, 0, 0])
    quad(b[1], b[2], t[2], t[1], [1, 0, 0])
  }
  box(0, 1.6, 9.62, 9.78, 0.035, 0.07, metal)
  box(1.35, 2.05, 9.74, 9.74, 0.13, 0.1, rgb(126, 130, 134)) // luminaire body
  return m.done()
})()

export const LAMP_LENS = (() => {
  const m = builder()
  const c = [1, 1, 1]
  const z = 9.735
  const a = [1.4, -0.11, z],
    b = [2.0, -0.11, z],
    cc = [2.0, 0.11, z],
    d = [1.4, 0.11, z]
  m.tri(a, b, cc, c, [0, 0, -1])
  m.tri(a, cc, d, c, [0, 0, -1])
  return m.done()
})()
