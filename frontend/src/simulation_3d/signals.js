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
const LAMPS = ['r', 'y', 'g']
const LAMP_OF = { green: 'g', yellow: 'y', red: 'r' }
// The approach names laneIndex.js uses, from the approach side in the network mapping
const SIDE = { north: 'N', east: 'E', south: 'S', west: 'W' }

/** The indication of every movement at time t: the last change at or before t. */
export function indicationsAt(changes, t) {
  let movements = changes[0]?.movements ?? {}
  for (const change of changes) {
    if (change.t <= t) movements = change.movements
    else break
  }
  return movements
}

// One lamp for a whole approach: all its movements change together (build_playback.py checks this).
// Red when there is no run yet.
const approachLamp = (movements, a) => LAMP_OF[movements[a.movementIds[0]]] ?? 'r'

/** Works out the pole, arm and head positions of every approach from signal_heads.json. Runs once. */
export function prepareSignals(signalHeads, signals) {
  const approaches = signalHeads.approaches.map((approach) => {
    const lanes = approach.lanes // rightmost lane first
    const o = lanes[0].position
    const [dx, dy] = toM(lanes[0].toward, o)
    const L = Math.hypot(dx, dy) || 1
    const f = [dx / L, dy / L],
      r = [f[1], -f[0]] // f is the travel direction, r points to the right of it
    const yaw = (Math.atan2(f[1], f[0]) * 180) / Math.PI

    // The pole stands at the right kerb, 1.5 m behind the stop line of the rightmost lane.
    const kerb = lanes[0].width_m / 2 + 1.2
    const poleM = [-f[0] * SETBACK + r[0] * kerb, -f[1] * SETBACK + r[1] * kerb]
    const poleLat = poleM[0] * r[0] + poleM[1] * r[1]

    // One head per lane, centred over the lane on the arm
    const heads = lanes.map((lane) => {
      const [hx, hy] = toM(lane.position, o)
      const lateral = hx * r[0] + hy * r[1]
      const along = lateral - poleLat // negative means left of the pole
      return { lane: lane.lane_id, lateral, m: [poleM[0] + r[0] * along, poleM[1] + r[1] * along] }
    })
    const far = Math.min(...heads.map((h) => h.lateral)) - 0.5
    const armLen = Math.max(1, poleLat - far)
    const armMid = [poleM[0] - (r[0] * armLen) / 2, poleM[1] - (r[1] * armLen) / 2]
    const P = (m, dfwd = 0, drt = 0) =>
      fromM([m[0] + f[0] * dfwd + r[0] * drt, m[1] + f[1] * dfwd + r[1] * drt], o)
    return {
      edge: lanes[0].lane_id.replace(/_\d+$/, ''), // the drawn road, for the approach highlight
      name: SIDE[approach.side],
      movementIds: approach.movement_ids,
      f,
      r,
      yaw,
      P,
      heads,
      poleM,
      pole: fromM(poleM, o),
      arm: { center: fromM(armMid, o), half: armLen / 2 },
    }
  })

  return { approaches, changes: signals?.changes ?? [], hardware: buildHardware(approaches) }
}

const poleHeadAt = (a) => a.poleM.map((v, i) => v - a.f[i] * (0.2 + 0.24 * K)) // the head on the pole, on the side facing traffic

/** The parts of the signals that never change: foundations, poles, arms and the head housings. */
function buildHardware(approaches) {
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

  for (const a of approaches) {
    poles.push({ position: a.pole })
    box([...a.arm.center, ARM_Z], a.yaw - 90, [a.arm.half, 0.14, 0.14], poleC) // mast arm
    for (const h of a.heads) {
      const top = HEAD_Z + 0.48 * K
      box([...a.P(h.m), (ARM_Z + top) / 2], a.yaw, [0.05, 0.05, (ARM_Z - top) / 2 + 0.05], poleC) // hanger
      head(a, h.m, HEAD_Z)
    }
    head(a, poleHeadAt(a), POLE_HEAD_Z)
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
function lensData(sig, movements) {
  const lit = [],
    dim = [],
    dots = []
  for (const a of sig.approaches) {
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
    const k = approachLamp(movements, a)
    for (const h of a.heads) add(h.m, HEAD_Z, k)
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
  const movements = indicationsAt(sig.changes, t)
  const lamps = sig.approaches.map((a) => approachLamp(movements, a))
  const key = lamps.join('|') + (top ? 'T' : 'P') + ENV.ambient.toFixed(2) // also rebuild when day/night changes
  if (key === cache.key && cache.sig === sig) return cache.layers

  const { lit, dim, dots } = lensData(sig, movements)
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
