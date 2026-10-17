import { ColumnLayer } from '@deck.gl/layers'
import { SimpleMeshLayer } from '@deck.gl/mesh-layers'
import { CubeGeometry, SphereGeometry } from '@luma.gl/engine'
import { toM, fromM } from './geo'
import { PALETTE, ENV, glowMaterial } from './palette'

// Traffic signals modelled on the mast-arm signals at Riyadh intersections. Each approach has a pole
// at the right kerb, an arm over the lanes with one head per lane, and a second head on the pole.
const cube = new CubeGeometry() // goes from -1 to 1, scaled per object
const sphere = new SphereGeometry({ nlat: 16, nlong: 24, radius: 1 })
// Signals are drawn at twice their real size so they are still easy to see next to 20 m wide roads.
const K = 2
const ARM_Z = 7.6,
  SETBACK = 1.5 // metres
const HEAD_Z = ARM_Z - 0.2 - 0.6 * K // the head hangs just under the arm
const POLE_HEAD_Z = 3.8
const LENS_DZ = 0.3 * K // spacing between the 300 mm lenses
const COMPASS = ['N', 'E', 'S', 'W']
const LAMPS = ['r', 'y', 'g']

/** Signal state string at time t. states is a sorted list of [time, string] pairs. */
export function stateAt(states, t) {
  let s = states[0]?.[1] ?? ''
  for (const [tt, st] of states) {
    if (tt <= t) s = st
    else break
  }
  return s
}
/** Turns one SUMO state character into 'r', 'y', 'g' or 'o' (off). */
export const cls = (ch) =>
  ch === 'G' || ch === 'g'
    ? 'g'
    : ch === 'y' || ch === 'Y' || ch === 'u'
      ? 'y'
      : ch === 'o' || ch === 'O'
        ? 'o'
        : 'r'

/** Colour of a whole approach. Green if any of its links is green, then yellow, otherwise red. */
export const approachClass = (state, links) => {
  const c = links.map((i) => cls(state[i]))
  return c.includes('g') ? 'g' : c.includes('y') ? 'y' : 'r'
}

/** Works out the pole, arm and head positions for every approach. Only runs once. */
export function prepareSignals(signalsJson, surface, center) {
  const laneWidth = {}
  for (const f of surface.features)
    if (f.properties.kind === 'lane') laneWidth[f.properties.id] = f.properties.width

  const controllers = signalsJson.traffic_lights.map((tl) => {
    const byEdge = {}
    for (const h of tl.heads) (byEdge[h.in_lane.replace(/_\d+$/, '')] ||= []).push(h)

    const approaches = Object.entries(byEdge).map(([edge, heads]) => {
      const o = heads[0].position
      const [dx, dy] = toM(heads[0].toward, o)
      const L = Math.hypot(dx, dy) || 1
      const f = [dx / L, dy / L],
        r = [f[1], -f[0]] // f is the travel direction, r points to the right of it
      const yaw = (Math.atan2(f[1], f[0]) * 180) / Math.PI
      const byLane = {}
      for (const h of heads) (byLane[h.in_lane] ||= []).push(h)

      // The pole stands at the right kerb, 1.5 m behind the stop line of the rightmost lane.
      const laneIdx = (id) => Number(id.match(/_(\d+)$/)[1])
      const rightLane = Object.keys(byLane).sort((a, b) => laneIdx(a) - laneIdx(b))[0]
      const [rx, ry] = toM(byLane[rightLane][0].position, o)
      const kerb = (laneWidth[rightLane] ?? 3.2) / 2 + 1.2
      const poleM = [rx - f[0] * SETBACK + r[0] * kerb, ry - f[1] * SETBACK + r[1] * kerb]
      const poleLat = poleM[0] * r[0] + poleM[1] * r[1]

      // One head per lane, centred over the lane on the arm. A lane with more than one movement still
      // gets a single head, which is fine because all movements of an approach change together in this plan.
      const placed = []
      for (const [lane, hs] of Object.entries(byLane)) {
        const [hx, hy] = toM(hs[0].position, o)
        const lateral = hx * r[0] + hy * r[1]
        const along = lateral - poleLat // negative means left of the pole
        placed.push({
          links: hs.map((h) => h.link_index),
          lane,
          lateral,
          m: [poleM[0] + r[0] * along, poleM[1] + r[1] * along],
        })
      }
      const far = Math.min(...placed.map((p) => p.lateral)) - 0.5
      const armLen = Math.max(1, poleLat - far)
      const armMid = [poleM[0] - (r[0] * armLen) / 2, poleM[1] - (r[1] * armLen) / 2]
      // Name the approach by where its stop line is compared to the junction centre.
      const [cx, cy] = toM(o, center)
      const bearing = ((Math.atan2(cx, cy) * 180) / Math.PI + 360) % 360
      const P = (m, dfwd = 0, drt = 0) =>
        fromM([m[0] + f[0] * dfwd + r[0] * drt, m[1] + f[1] * dfwd + r[1] * drt], o)
      return {
        edge,
        f,
        r,
        yaw,
        P,
        // The arms are diagonal, so we use the same names as the signal documentation:
        // NE arm is East, SE is South, SW is West and NW is North.
        name: COMPASS[(Math.floor(bearing / 90) + 1) % 4],
        links: placed.flatMap((p) => p.links),
        heads: placed,
        poleM,
        pole: fromM(poleM, o),
        arm: { center: fromM(armMid, o), half: armLen / 2 },
      }
    })
    return { id: tl.tls_id, cycle: tl.cycle_s ?? 120, states: tl.states, approaches }
  })

  return { controllers, tEnd: signalsJson.t_end ?? 120, hardware: buildHardware(controllers) }
}

const poleHeadAt = (a) => a.poleM.map((v, i) => v - a.f[i] * (0.2 + 0.24 * K)) // the head on the pole, on the side facing traffic

/** The parts of the signals that never change: foundations, poles, arms and the head housings. */
function buildHardware(controllers) {
  const boxes = []
  const poles = []
  const { housing, pole: poleC, border, plate } = PALETTE.signal
  const box = (position, yaw, scale, color) => boxes.push({ position, yaw, scale, color })

  // One signal head with three lenses, facing the oncoming traffic.
  // The sizes below are real sizes in metres, scaled up by K.
  const head = (a, m, z) => {
    const B = (dfwd, drt, dz, sx, sy, sz, col) =>
      box([...a.P(m, dfwd * K, drt * K), z + dz * K], a.yaw, [sx * K, sy * K, sz * K], col)
    B(0, 0, 0, 0.12, 0.17, 0.48, housing)
    B(0.1, 0, 0, 0.012, 0.29, 0.6, plate) // backplate
    for (const [dl, dz, sl, sz] of [
      [0, 0.585, 0.29, 0.03],
      [0, -0.585, 0.29, 0.03],
      [0.275, 0, 0.03, 0.6],
      [-0.275, 0, 0.03, 0.6],
    ])
      B(0.085, dl, dz, 0.006, sl, sz, border) // yellow border around the backplate
    LAMPS.forEach((_, i) => {
      const lz = 0.3 - i * 0.3
      B(-0.21, 0, lz + 0.12, 0.09, 0.13, 0.008, housing) // visor top
      B(-0.19, 0.125, lz + 0.04, 0.07, 0.006, 0.08, housing) // visor sides
      B(-0.19, -0.125, lz + 0.04, 0.07, 0.006, 0.08, housing)
    })
  }

  for (const c of controllers) {
    for (const a of c.approaches) {
      poles.push({ position: a.pole })
      box([...a.arm.center, ARM_Z], a.yaw - 90, [a.arm.half, 0.14, 0.14], poleC) // mast arm
      for (const h of a.heads) {
        const top = HEAD_Z + 0.48 * K
        box([...a.P(h.m), (ARM_Z + top) / 2], a.yaw, [0.05, 0.05, (ARM_Z - top) / 2 + 0.05], poleC) // hanger
        head(a, h.m, HEAD_Z)
      }
      head(a, poleHeadAt(a), POLE_HEAD_Z)
    }
  }
  return [
    new ColumnLayer({
      id: 'signal-foundations',
      data: poles,
      getPosition: (d) => d.position,
      radius: 0.5,
      diskResolution: 24,
      extruded: true,
      getElevation: 0.4,
      getFillColor: PALETTE.concrete,
    }),
    new ColumnLayer({
      id: 'signal-poles',
      data: poles,
      getPosition: (d) => d.position,
      radius: 0.2,
      diskResolution: 24,
      extruded: true,
      getElevation: ARM_Z + 0.4,
      getFillColor: poleC,
    }),
    new SimpleMeshLayer({
      id: 'signal-hardware',
      data: boxes,
      mesh: cube,
      getPosition: (d) => d.position,
      getOrientation: (d) => [0, d.yaw, 0],
      getScale: (d) => d.scale,
      getColor: (d) => d.color,
    }),
  ]
}

/** Lens positions and colors for the current signal states. */
function lensData(sig, states) {
  const lit = [],
    dim = [],
    dots = []
  sig.controllers.forEach((c, ci) => {
    const state = states[ci]
    for (const a of c.approaches) {
      const add = (m, z, k) => {
        const front = a.P(m, -0.125 * K)
        const g1 = a.P(m, -0.152 * K),
          g2 = a.P(m, -0.32 * K),
          g3 = a.P(m, -0.33 * K) // the glow sits in front of the visor
        LAMPS.forEach((lamp, i) => {
          const lz = z + LENS_DZ - i * LENS_DZ
          ;(k === lamp ? lit : dim).push({
            position: [...front, lz],
            glow1: [...g1, lz],
            glow2: [...g2, lz],
            glow3: [...g3, lz],
            yaw: a.yaw,
            lamp,
          })
        })
      }
      for (const h of a.heads) add(h.m, HEAD_Z, approachClass(state, h.links))
      const k = approachClass(state, a.links)
      add(poleHeadAt(a), POLE_HEAD_Z, k)
      // Symbol for the top view. It lies along the arm with red on the driver's left.
      const icon = {
        k,
        yaw: a.yaw - 90,
        center: a.P(a.poleM, 0, -a.arm.half),
        half: a.arm.half,
        lamps: LAMPS.map((lamp, i) => ({
          lamp,
          on: lamp === k,
          position: [...a.P(a.poleM, 0, -a.arm.half + (i - 1) * 1.3 * T), ARM_Z + 1.0],
        })),
      }
      dots.push(icon)
    }
  })
  return { lit, dim, dots }
}

// In the top view you can't see the lenses, so each arm gets a small flat signal with the active lamp lit.
const T = 1.3 // icon scale
// Additive blending, so the glow brightens what is behind it like a real lamp.
const LIGHT = {
  depthWriteEnabled: false,
  blend: true,
  blendColorOperation: 'add',
  blendColorSrcFactor: 'src-alpha',
  blendColorDstFactor: 'one',
  blendAlphaOperation: 'add',
  blendAlphaSrcFactor: 'one',
  blendAlphaDstFactor: 'one',
}
const hot = (c) => c.map((v) => Math.round(v + (255 - v) * 0.55)) // centre of a lit lamp, almost white

function topLayers(icons, top) {
  const { lit: litC, dim: dimC, housing } = PALETTE.signal
  const lamps = icons.flatMap((d) => d.lamps.map((l) => ({ ...l, yaw: d.yaw })))
  const on = lamps.filter((l) => l.on)
  const z = (d, dz) => [d.position[0], d.position[1], ARM_Z + dz]
  return [
    new SimpleMeshLayer({
      id: 'signal-top-housing',
      data: icons,
      mesh: cube,
      visible: top,
      getPosition: (d) => [...d.lamps[1].position.slice(0, 2), ARM_Z + 0.9],
      getOrientation: (d) => [0, d.yaw, 0],
      getScale: [2.1 * T, 0.8 * T, 0.08],
      getColor: housing,
    }),
    new SimpleMeshLayer({
      id: 'signal-top-lamps',
      data: lamps,
      mesh: sphere,
      material: glowMaterial(),
      visible: top,
      getPosition: (d) => z(d, 1.05),
      getScale: [0.5 * T, 0.5 * T, 0.04],
      getColor: (d) => (d.on ? litC[d.lamp] : dimC[d.lamp]),
    }),
    new SimpleMeshLayer({
      id: 'signal-top-core',
      data: on,
      mesh: sphere,
      material: glowMaterial(),
      visible: top,
      getPosition: (d) => z(d, 1.08),
      getScale: [0.22 * T, 0.22 * T, 0.02],
      getColor: (d) => hot(litC[d.lamp]),
    }),
    new SimpleMeshLayer({
      id: 'signal-top-glow',
      data: on,
      mesh: sphere,
      material: glowMaterial(),
      visible: top,
      parameters: LIGHT,
      getPosition: (d) => z(d, 1.1),
      getScale: [1.05 * T, 1.05 * T, 0.02],
      getColor: (d) => [...litC[d.lamp], 70],
    }),
    new SimpleMeshLayer({
      id: 'signal-top-glow-outer',
      data: on,
      mesh: sphere,
      material: glowMaterial(),
      visible: top,
      parameters: LIGHT,
      getPosition: (d) => z(d, 1.11),
      getScale: [1.6 * T, 1.6 * T, 0.02],
      getColor: (d) => [...litC[d.lamp], 30],
    }),
  ]
}

// Only rebuild the layers when a signal changes color or the view changes, not on every frame.
let cache = { key: null, sig: null, layers: [] }

export function signalLayers(sig, t, { top = false } = {}) {
  const states = sig.controllers.map((c) => stateAt(c.states, t))
  const key = states.join('|') + (top ? 'T' : 'P') + ENV.ambient.toFixed(2) // also rebuild when day/night changes
  if (key === cache.key && cache.sig === sig) return cache.layers

  const { lit, dim, dots } = lensData(sig, states)
  const { lit: litC, dim: dimC } = PALETTE.signal
  const layers = [
    ...sig.hardware,
    new SimpleMeshLayer({
      id: 'signal-lens-dim',
      data: dim,
      mesh: sphere,
      getPosition: (d) => d.position,
      getOrientation: (d) => [0, d.yaw, 0],
      getScale: [0.02 * K, 0.1 * K, 0.1 * K],
      getColor: (d) => dimC[d.lamp],
    }),
    new SimpleMeshLayer({
      id: 'signal-lens-lit',
      data: lit,
      mesh: sphere,
      material: glowMaterial(),
      getPosition: (d) => d.position,
      getOrientation: (d) => [0, d.yaw, 0],
      getScale: [0.025 * K, 0.105 * K, 0.105 * K],
      getColor: (d) => litC[d.lamp],
    }),
    // Each lit lens gets a bright centre and two layers of glow around it.
    new SimpleMeshLayer({
      id: 'signal-lens-core',
      data: lit,
      mesh: sphere,
      material: glowMaterial(),
      getPosition: (d) => d.glow1,
      getOrientation: (d) => [0, d.yaw, 0],
      getScale: [0.006 * K, 0.05 * K, 0.05 * K],
      getColor: (d) => hot(litC[d.lamp]),
    }),
    new SimpleMeshLayer({
      id: 'signal-lens-glow',
      data: lit,
      mesh: sphere,
      material: glowMaterial(),
      parameters: LIGHT,
      getPosition: (d) => d.glow2,
      getOrientation: (d) => [0, d.yaw, 0],
      getScale: [0.004 * K, 0.2 * K, 0.2 * K],
      getColor: (d) => [...litC[d.lamp], 80],
    }),
    new SimpleMeshLayer({
      id: 'signal-lens-glow-outer',
      data: lit,
      mesh: sphere,
      material: glowMaterial(),
      parameters: LIGHT,
      getPosition: (d) => d.glow3,
      getOrientation: (d) => [0, d.yaw, 0],
      getScale: [0.004 * K, 0.34 * K, 0.34 * K],
      getColor: (d) => [...litC[d.lamp], 32],
    }),
    ...topLayers(dots, top),
  ]
  cache = { key, sig, layers }
  return layers
}
