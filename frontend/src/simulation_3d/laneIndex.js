import { toM } from './geo'

// Lane info and live numbers for the lane panel (components/LanePanel.jsx).
// sim.json doesn't say which lane a car is on, so we count a car on a lane if its centre is inside the lane outline.
const ARM = { N: 'North', E: 'East', S: 'South', W: 'West' }
const COMPASS = ['N', 'E', 'S', 'W']
const MOVE = { s: 'Through', l: 'Left', r: 'Right', t: 'U-turn', L: 'Left', R: 'Right' }
export const QUEUE_KMH = 5 // under 5 km/h counts as queued, same as SUMO's default
export const SIG = {
  g: ['Green', '#1fb85a'],
  y: ['Yellow', '#f0a500'],
  r: ['Red', '#e03131'],
  o: ['Off', '#9ca3af'],
}

// Tell the two main roads apart by direction. Prince Turki runs NW to SE (about 131°), Imam Saud SW to NE (about 40 to 66°).
function roadName(axis) {
  if (axis >= 95 && axis <= 170) return 'Prince Turki bin Abdulaziz Al-Awwal Rd'
  if (axis >= 20 && axis <= 85) return 'Imam Saud bin Abdulaziz Rd'
  return 'Side street'
}

// Lane info that doesn't change over time, so we work it out once.
export function prepareLaneIndex({ surface, detail, arrows, signals, center }) {
  const centre = {},
    dirs = {},
    sig = {},
    perEdge = {}
  for (const f of detail?.features ?? [])
    if (f.properties.kind === 'lane_centre') centre[f.properties.lane] = f.geometry.coordinates
  for (const f of arrows?.features ?? []) dirs[f.properties.lane] = f.properties.dirs
  for (const c of signals?.controllers ?? [])
    for (const a of c.approaches) for (const h of a.heads) sig[h.lane] = { c, links: h.links }
  for (const f of surface.features)
    if (f.properties.kind === 'lane')
      perEdge[f.properties.edge] = (perEdge[f.properties.edge] ?? 0) + 1

  const lanes = {}
  for (const f of surface.features) {
    const p = f.properties
    if (p.kind !== 'lane') continue
    const ring = f.geometry.coordinates[0].map((c) => toM(c, center))
    const path = (centre[p.id] ?? []).map((c) => toM(c, center))
    const cum = [0]
    for (let i = 1; i < path.length; i++)
      cum.push(
        cum.at(-1) +
          Math.hypot(path.at(i)[0] - path.at(i - 1)[0], path.at(i)[1] - path.at(i - 1)[1]),
      )
    const length = cum.at(-1) || null
    let road = '—',
      arm = null,
      heading = null
    if (path.length > 1) {
      const [a, b] = [path.at(0), path.at(-1)]
      road = roadName(((Math.atan2(b[0] - a[0], b[1] - a[1]) * 180) / Math.PI + 360) % 180)
      const mid = path.at(path.length >> 1)
      const bearing = ((Math.atan2(mid[0], mid[1]) * 180) / Math.PI + 360) % 360
      arm = ARM[COMPASS[(Math.floor(bearing / 90) + 1) % 4]] // same arm names as in the signal plan
      heading = Math.hypot(...b) < Math.hypot(...a) ? 'in' : 'out'
    }
    const idx = Number(p.id.slice(p.id.lastIndexOf('_') + 1))
    lanes[p.id] = {
      ...p,
      ring,
      path,
      cum,
      length,
      road,
      arm,
      heading,
      idx,
      count: perEdge[p.edge] ?? 1,
      moves: dirs[p.id] ? [...new Set([...dirs[p.id]].map((d) => MOVE[d]).filter(Boolean))] : null,
      signal: sig[p.id] ?? null,
    }
  }
  return { lanes, center }
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
// How far along the lane centre line the closest point to p is.
function along(lane, p) {
  let best = Infinity,
    s = 0
  const P = lane.path
  for (let i = 1; i < P.length; i++) {
    const [ax, ay] = P[i - 1],
      [bx, by] = P[i],
      dx = bx - ax,
      dy = by - ay,
      L2 = dx * dx + dy * dy || 1
    const k = Math.max(0, Math.min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / L2))
    const d = Math.hypot(ax + dx * k - p[0], ay + dy * k - p[1])
    if (d < best) {
      best = d
      s = lane.cum[i - 1] + Math.sqrt(L2) * k
    }
  }
  return s
}

// Live numbers for one lane. vehicles is the output of vehicleStates() for the current time.
export function laneStats(index, laneId, vehicles) {
  const lane = index.lanes[laneId]
  if (!lane) return null
  const on = vehicles.filter((v) => inside(toM(v.position, index.center), lane.ring))
  const queued = on.filter((v) => v.speed * 3.6 < QUEUE_KMH)
  let queue = 0
  if (lane.length && lane.heading !== 'out') {
    // Queue length goes from the stop line back to the last queued car. A gap over 10 m ends the queue.
    const ahead = queued
      .map((v) => lane.length - along(lane, toM(v.position, index.center)))
      .sort((a, b) => a - b)
    let rear = 0
    for (const d of ahead) {
      // d is the distance from the stop line to the car centre, 2.25 m is half a car length
      if (d - 2.25 - rear > (rear ? 10 : 20)) break
      rear = d + 2.25
    }
    queue = Math.min(rear, lane.length)
  }
  const avg = on.length ? (on.reduce((s, v) => s + v.speed, 0) / on.length) * 3.6 : null
  return { lane, n: on.length, queued: queued.length, queue, avg }
}

// The lanes that belong to each approach of the signal: start at the lanes that end at the stop
// line and walk back upstream, lane by lane, as long as the road carries straight on. A lane that
// joins at an angle (a side street or parking access) is not followed, so only the approach road
// itself is picked. Returns { North: Set(laneIds), East: ..., ... }.
const ARM_NAMES = { N: 'North', E: 'East', S: 'South', W: 'West' }
export function approachLanes(index, signals, maxDistance = 200) {
  const lanes = Object.values(index.lanes).filter((l) => l.path.length > 1)
  const dir = (a, b) => Math.atan2(b[1] - a[1], b[0] - a[0])
  const turn = (a, b) => Math.abs(((a - b + 3 * Math.PI) % (2 * Math.PI)) - Math.PI)
  const STRAIGHT = (35 * Math.PI) / 180
  // median openings (junctions where cars can turn left or make a U-turn): the approach stops
  // there, so it doesn't run on past the opening. Right-turn slip lanes don't stop it.
  const junctionOf = (id) => id.slice(1).replace(/_\d+_\d+$/, '')
  const signedTurn = (a, b) => ((a - b + 3 * Math.PI) % (2 * Math.PI)) - Math.PI
  const turning = new Set()
  for (const l of lanes) {
    if (!l.internal || l.path.length < 2) continue
    const t = signedTurn(dir(l.path.at(-2), l.path.at(-1)), dir(l.path[0], l.path[1]))
    if (t > STRAIGHT) turning.add(junctionOf(l.id)) // positive = turning left (counter-clockwise)
  }
  const result = {}
  for (const c of signals?.controllers ?? [])
    for (const a of c.approaches) {
      const arm = ARM_NAMES[a.name]
      const found = (result[arm] ??= new Set())
      const queue = lanes.filter((l) => l.id.startsWith(`${a.edge}_`) && !l.internal)
      queue.forEach((l) => found.add(l.id))
      while (queue.length) {
        const lane = queue.shift()
        const start = lane.path[0]
        if (Math.hypot(...start) > maxDistance) continue
        const startDir = dir(lane.path[0], lane.path[1])
        for (const k of lanes) {
          if (found.has(k.id)) continue
          const end = k.path.at(-1)
          if (Math.hypot(end[0] - start[0], end[1] - start[1]) > 1.0) continue
          if (turn(dir(k.path.at(-2), end), startDir) > STRAIGHT) continue
          // a short connector that starts at an angle comes from a side street
          if (k.internal && turn(dir(k.path[0], k.path[1]), startDir) > STRAIGHT) continue
          if (k.internal && turning.has(junctionOf(k.id)) && !k.id.includes('cluster')) continue
          // a long road piece that starts far away belongs to the road further back, not to the
          // approach: it is left out so only the part near the signal is highlighted
          if (Math.hypot(...k.path[0]) > maxDistance) continue
          found.add(k.id)
          queue.push(k)
        }
      }
    }
  return result
}
