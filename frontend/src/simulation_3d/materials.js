import { FillStyleExtension } from '@deck.gl/extensions'

// Textures for the flat surfaces (asphalt, sand, pavers, concrete). They are generated once in the
// browser with a fixed seed, so we don't need image files. Sizes are in metres so they stay fixed on the ground.
const T = 512 // pixels per tile

// Position of each tile in the atlas and how many metres one tile covers.
const TILES = {
  asphalt: { col: 0, row: 0, metres: 9 },
  sand: { col: 1, row: 0, metres: 26 }, // open ground: big tile so it doesn't visibly repeat
  pavers: { col: 2, row: 0, metres: 6.4 }, // 0.4 by 0.2 m concrete pavers
  concrete: { col: 3, row: 0, metres: 6 },
  parking: { col: 0, row: 1, metres: 9 },
  apron: { col: 1, row: 1, metres: 6.4 }, // 0.8 m stone tiles
  slab: { col: 2, row: 1, metres: 12 }, // concrete for the tunnel roof
  variation: { col: 3, row: 1, metres: 140 }, // big light and dark patches, used as a mask
  kerb: { col: 0, row: 2, metres: 4 }, // smooth precast kerb stone
}

// Simple noise functions with a fixed seed. The noise wraps around so the tiles repeat without seams.
function rng(seed) {
  let s = seed >>> 0
  return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296
}
function lattice(n, seed) {
  const r = rng(seed)
  return Float32Array.from({ length: n * n }, r)
}
function makeNoise(seed) {
  const cache = {}
  return (x, y, period) => {
    // x and y go from 0 to period and wrap around
    const L = (cache[period] ||= lattice(period, seed + period * 7919))
    const x0 = Math.floor(x),
      y0 = Math.floor(y),
      fx = x - x0,
      fy = y - y0
    const x1 = (x0 + 1) % period,
      y1 = (y0 + 1) % period
    const sx = fx * fx * (3 - 2 * fx),
      sy = fy * fy * (3 - 2 * fy)
    const a = L.at(y0 * period + x0),
      b = L.at(y0 * period + x1),
      c = L.at(y1 * period + x0),
      d = L.at(y1 * period + x1)
    return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy
  }
}
function fbm(noise, u, v, base, oct) {
  // u and v go from 0 to 1
  let s = 0,
    amp = 0.5,
    norm = 0,
    p = base
  for (let o = 0; o < oct; o++) {
    s += amp * noise(u * p, v * p, p)
    norm += amp
    amp *= 0.5
    p *= 2
  }
  return s / norm
}
const clamp = (v) => (v < 0 ? 0 : v > 255 ? 255 : v)

function paintTile(img, W, ox, oy, fn) {
  const d = img.data
  for (let y = 0; y < T; y++)
    for (let x = 0; x < T; x++) {
      const [r, g, b, a = 255] = fn(x, y)
      const i = ((oy + y) * W + ox + x) * 4
      d[i] = clamp(r)
      d[i + 1] = clamp(g)
      d[i + 2] = clamp(b)
      d[i + 3] = a
    }
}

function buildAtlas() {
  const W = T * 4,
    H = T * 3
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  const ctx = canvas.getContext('2d')
  const img = ctx.createImageData(W, H)
  const n1 = makeNoise(11),
    n2 = makeNoise(23),
    n3 = makeNoise(37)
  const grain = rng(5)
  const at = (k) => [TILES[k].col * T, TILES[k].row * T]

  // Asphalt: mid charcoal grey (not black) with a fine aggregate grain and very soft mottling.
  // Low contrast on purpose, so it reads as one even surface from any distance.
  const asphalt = (light) => (x, y) => {
    const u = x / T,
      v = y / T
    const low = fbm(n1, u, v, 3, 4) - 0.5
    const mid = fbm(n2, u, v, 24, 3) - 0.5
    const g = (grain() - 0.5) * 10
    const r = grain()
    const stone = r < 0.03 ? 14 + grain() * 10 : r > 0.985 ? -10 : 0
    const base = light + low * 7 + mid * 5 + g + stone
    return [base, base + 1, base + 4]
  }
  paintTile(img, W, ...at('asphalt'), asphalt(64)) // same grey as the roads in the tunnel
  paintTile(img, W, ...at('parking'), asphalt(118))

  // Open ground: a muted warm grey (dry compacted earth, not yellow sand) with fine gravel and
  // very gentle tonal changes. No ripples or stripes, which looked artificial.
  paintTile(img, W, ...at('sand'), (x, y) => {
    const u = x / T,
      v = y / T
    const low = fbm(n1, u, v, 2, 5) - 0.5,
      mid = fbm(n3, u, v, 12, 4) - 0.5,
      fine = fbm(n2, u, v, 64, 2) - 0.5
    const r = grain()
    const gravel = r < 0.05 ? -12 - grain() * 10 : r > 0.97 ? 10 : 0
    const t = low * 14 + mid * 8 + fine * 6 + gravel + (grain() - 0.5) * 6
    return [192 + t, 184 + t * 0.97, 168 + t * 0.92]
  })

  // Concrete pavers, 0.4 by 0.2 m in a running bond, light grey with soft joints
  const brick = makeNoise(71)
  paintTile(img, W, ...at('pavers'), (x, y) => {
    const row = Math.floor(y / 16),
      xs = x + (row % 2) * 16,
      col = Math.floor(xs / 32) % 16
    const joint = y % 16 === 0 || xs % 32 === 0
    const tone = (brick(col + 0.5, row + 0.5, 32) - 0.5) * 8
    const g = (grain() - 0.5) * 6,
      low = (fbm(n1, x / T, y / T, 3, 3) - 0.5) * 8
    const b = joint ? 186 : 212 + tone + g + low
    return [b, b - 2, b - 6]
  })

  // Median concrete: a touch darker than the sidewalk, saw joint every 3 m
  paintTile(img, W, ...at('concrete'), (x, y) => {
    const u = x / T,
      v = y / T
    const low = fbm(n2, u, v, 5, 4) - 0.5,
      g = (grain() - 0.5) * 6
    const joint = x % 256 < 2 || y % 256 < 2
    const b = joint ? 176 : 196 + low * 10 + g
    return [b, b - 1, b - 4]
  })

  // Kerb stone: smooth, light, with a faint joint every metre
  paintTile(img, W, ...at('kerb'), (x, y) => {
    const low = fbm(n3, x / T, y / T, 4, 3) - 0.5,
      g = (grain() - 0.5) * 4
    const joint = x % 128 < 2
    const b = joint ? 200 : 226 + low * 6 + g
    return [b, b - 1, b - 3]
  })

  // 0.8 m light stone tiles in front of buildings
  const slab = makeNoise(91)
  paintTile(img, W, ...at('apron'), (x, y) => {
    const tx = Math.floor(x / 64),
      ty = Math.floor(y / 64),
      joint = x % 64 < 2 || y % 64 < 2
    const tone = (slab(tx + 0.5, ty + 0.5, 8) - 0.5) * 8,
      g = (grain() - 0.5) * 5
    if (joint) return [190, 187, 180]
    return [218 + tone + g, 213 + tone + g, 202 + tone + g]
  })

  // Darker, older looking concrete for the tunnel roof.
  paintTile(img, W, ...at('slab'), (x, y) => {
    const u = x / T,
      v = y / T,
      low = fbm(n3, u, v, 5, 4) - 0.5,
      g = (grain() - 0.5) * 10
    const b = 168 + low * 22 + g
    return [b, b - 1, b - 4]
  })

  // Large patches stored only in the alpha channel. Used to break up the repeating textures.
  paintTile(img, W, ...at('variation'), (x, y) => {
    const u = x / T,
      v = y / T,
      f = fbm(n1, u, v, 3, 5)
    return [255, 255, 255, Math.round(Math.max(0, f - 0.42) * 2.2 * 255)]
  })

  ctx.putImageData(img, 0, 0)
  // Copy each tile to its own canvas. With one shared atlas the neighbouring tiles bleed into the
  // edges and show up as thin lines on the ground.
  const tiles = {}
  for (const [k, t] of Object.entries(TILES)) {
    const c = document.createElement('canvas')
    c.width = T
    c.height = T
    c.getContext('2d').drawImage(canvas, t.col * T, t.row * T, T, T, 0, 0, T, T)
    tiles[k] = { canvas: c, mapping: { [k]: { x: 0, y: 0, width: T, height: T } } }
  }
  return tiles
}

let ATLAS = null
const atlas = () => (ATLAS ||= buildAtlas())

/** Props that give a polygon layer the texture of the given material. */
export function material(name) {
  const { canvas: url, mapping } = atlas()[name]
  return {
    extensions: [new FillStyleExtension({ pattern: true })],
    fillPatternAtlas: url,
    fillPatternMapping: mapping,
    fillPatternMask: false,
    fillPatternSizeUnits: 'meters',
    getFillPattern: () => name,
    getFillPatternScale: TILES[name].metres / T,
    getFillPatternOffset: [0, 0],
    getFillColor: [255, 255, 255, 255],
    // Flat surfaces don't cast shadows, so we skip them in the shadow pass to save work.
    shadowEnabled: false,
  }
}

/** Big light and dark patches over a surface. color is the tint and its alpha is how strong it is. */
export function variation(color, { scale = 1, offset = [0, 0] } = {}) {
  const { canvas: url, mapping } = atlas().variation
  return {
    extensions: [new FillStyleExtension({ pattern: true })],
    fillPatternAtlas: url,
    fillPatternMapping: mapping,
    fillPatternMask: true,
    fillPatternSizeUnits: 'meters',
    getFillPattern: () => 'variation',
    getFillPatternScale: (TILES.variation.metres / T) * scale,
    getFillPatternOffset: offset,
    getFillColor: color,
    shadowEnabled: false,
  }
}
