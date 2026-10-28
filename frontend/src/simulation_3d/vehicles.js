import { SimpleMeshLayer } from '@deck.gl/mesh-layers'
import { fromM, toM } from './geo'
import { ENV, glowMaterial } from './palette'
import { CAR_MODELS, MODEL_SHARE, PAINT_SHARE } from './vehicleModels'

// Each SUMO car is drawn with one of the car models (sedan, SUV, crossover, pickup or Defender),
// picked from its id so it stays the same car for the whole trip. SUMO gives the front bumper
// position and a heading (0 = north, clockwise), so the model is placed behind the front bumper
// by its own length. We interpolate between the 0.5 s samples so the motion looks smooth.
// Brake lights use SUMO signal bit 8, indicators use bits 1 (right) and 2 (left).

// same number for the same id every time
function hashOf(id, salt) {
  let h = salt
  for (const c of id) h = (Math.imul(h, 31) + c.charCodeAt(0)) >>> 0
  h ^= h >>> 15
  h = Math.imul(h, 2246822519) >>> 0
  return (h ^ (h >>> 13)) >>> 0
}
// pick from a list by share, using a number from 0 to 1
function pickByShare(items, shareOf, u) {
  const total = items.reduce((s, it) => s + shareOf(it), 0)
  let acc = 0
  for (const it of items) {
    acc += shareOf(it) / total
    if (u < acc) return it
  }
  return items.at(-1)
}

function carOf(id) {
  const model = pickByShare(CAR_MODELS, (m) => MODEL_SHARE[m.name], hashOf(id, 7) / 2 ** 32)
  const { color } = pickByShare(PAINT_SHARE, (p) => p.share, hashOf(id, 11) / 2 ** 32)
  // small difference in shade between cars of the same color, like real paint and dirt
  const shade = 0.96 + ((hashOf(id, 13) % 1000) / 1000) * 0.07
  return { model, paint: color.map((c) => Math.min(255, Math.round(c * shade))) }
}

// Shiny paint, glass and chrome, and matte rubber and plastic.
const CARPAINT = { ambient: 0.38, diffuse: 0.6, shininess: 80, specularColor: [165, 165, 165] }
const GLOSS = { ambient: 0.35, diffuse: 0.45, shininess: 120, specularColor: [215, 220, 226] }
const MATTE = { ambient: 0.45, diffuse: 0.5, shininess: 12, specularColor: [24, 24, 24] }

const LANE_CHANGE_S = 2 // how long a lane change takes on screen, in seconds
const JUMP_M = 2.5 // a sideways step this big between two samples is a lane change…
const STRAIGHT_DEG = 5 // …when the car keeps its heading

// SUMO moves a car to the next lane in one step (instant lane changes keep the KPIs right). On
// screen that looks like a jump, so the sideways move is spread over LANE_CHANGE_S, half before
// and half after the step. Only the drawing changes; the files keep SUMO's positions.
function smoothLaneChanges(trip) {
  const path = trip.path.map((p) => [...p])
  const ts = trip.timestamps
  for (let k = 1; k < path.length; k++) {
    const turn = Math.abs(((trip.angles[k] - trip.angles[k - 1] + 540) % 360) - 180)
    if (turn >= STRAIGHT_DEG) continue
    const [dx, dy] = toM(trip.path[k], trip.path[k - 1])
    const h = (trip.angles[k - 1] * Math.PI) / 180
    const side = dx * Math.cos(h) - dy * Math.sin(h) // metres to the right of the heading
    if (Math.abs(side) < JUMP_M) continue
    const shift = [Math.cos(h) * side, -Math.sin(h) * side] // the sideways part of the step
    for (let i = 0; i < path.length; i++) {
      const w = (ts[i] - (ts[k] - LANE_CHANGE_S / 2)) / LANE_CHANGE_S // 0 to 1 across the change
      if (w <= 0 || w >= 1) continue
      const part = i < k ? w : w - 1 // before the step: start moving over; after it: still catching up
      path[i] = fromM([shift[0] * part, shift[1] * part], path[i])
    }
  }
  return { ...trip, path }
}

// Prepare the trips once. Each frame then finds the right sample with a binary search.
export function prepareVehicles(sim) {
  const trips = (sim?.trips ?? [])
    .filter((t) => t.timestamps?.length > 1)
    .map((t) => ({ ...smoothLaneChanges(t), ...carOf(t.vehicle_id) }))
  return { trips, tEnd: sim?.t_end ?? 0 }
}

// front bumper position at time t, interpolated between the samples
function frontAt(trip, t) {
  const ts = trip.timestamps
  let lo = 0,
    hi = ts.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (ts.at(mid) <= t) lo = mid
    else hi = mid
  }
  const f =
    ts.at(hi) === ts.at(lo)
      ? 0
      : Math.min(1, Math.max(0, (t - ts.at(lo)) / (ts.at(hi) - ts.at(lo))))
  const a = trip.path.at(lo),
    b = trip.path.at(hi)
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
}

function sample(trip, t) {
  const ts = trip.timestamps
  if (t < ts.at(0) || t > ts.at(-1)) return null
  let lo = 0,
    hi = ts.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (ts.at(mid) <= t) lo = mid
    else hi = mid
  }
  const f = ts.at(hi) === ts.at(lo) ? 0 : (t - ts.at(lo)) / (ts.at(hi) - ts.at(lo))
  const a = trip.path.at(lo),
    b = trip.path.at(hi)
  let da = ((trip.angles.at(hi) - trip.angles.at(lo) + 540) % 360) - 180 // shortest turn
  const angle = trip.angles.at(lo) + da * f
  const z = (trip.z?.at(lo) ?? 0) + ((trip.z?.at(hi) ?? 0) - (trip.z?.at(lo) ?? 0)) * f
  const front = [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
  const L = trip.model.length
  // Find the rear bumper by walking back along the road the car has just driven, so on a turn the
  // car follows the curve instead of sliding sideways. Without enough history (start of a trip),
  // fall back to SUMO's heading for the rest.
  let need = L,
    prev = front,
    rear = null,
    jump = false
  for (let i = lo; i >= 0 && need > 0; i--) {
    const p = trip.path.at(i)
    const [ex, ey] = toM(p, prev)
    const d = Math.hypot(ex, ey)
    // a step that goes sideways to the car's own heading is a lane-change jump in the data
    if (d > 1 && i < lo) {
      const stepYaw = (Math.atan2(-ey, -ex) * 180) / Math.PI
      const own = 90 - (trip.angles.at(i + 1) ?? 0)
      if (Math.abs(((((stepYaw - own) % 360) + 540) % 360) - 180) > 50) jump = true
    }
    if (d >= need) {
      rear = fromM([(ex * need) / d, (ey * need) / d], prev)
      need = 0
    } else if (d > 0) {
      need -= d
      prev = p
    }
  }
  // Tilt the car up or down on the ramps based on the height change.
  const [dx, dy] = toM(b, a),
    run = Math.hypot(dx, dy)
  const pitch =
    run > 0.3 ? (Math.atan2((trip.z?.at(hi) ?? 0) - (trip.z?.at(lo) ?? 0), run) * 180) / Math.PI : 0
  const rad = (angle * Math.PI) / 180 // SUMO heading in radians
  if (!rear) rear = fromM([-Math.sin(rad) * need, -Math.cos(rad) * need], prev)
  const [hx, hy] = toM(front, rear)
  const pathYaw = (Math.atan2(hy, hx) * 180) / Math.PI
  const sumoYaw = 90 - angle
  const off = Math.abs(((((pathYaw - sumoYaw) % 360) + 540) % 360) - 180)
  // Follow the driven path, unless it has a sideways jump in it (a lane change in the data):
  // then following it would turn the car across the lanes, so SUMO's heading is used instead.
  const usePath = !jump && Math.hypot(hx, hy) > 0.5 && off < 60
  // Otherwise, while moving, point the car where it is actually going over the last 0.6 s (SUMO's
  // heading is only sampled every 0.5 s and lags on turns, which made cars slide sideways).
  // Standing cars keep SUMO's heading, so a sideways jump in the data can't spin them round.
  let yaw = sumoYaw
  if (usePath) yaw = pathYaw
  else if ((trip.speeds?.at(lo) ?? 0) > 1.5) {
    const back = frontAt(trip, Math.max(ts.at(0), t - 0.6))
    const [mx, my] = toM(front, back)
    const moveYaw = (Math.atan2(my, mx) * 180) / Math.PI
    const diff = Math.abs(((((moveYaw - sumoYaw) % 360) + 540) % 360) - 180)
    if (Math.hypot(mx, my) > 0.8 && diff < 35) yaw = moveYaw
  }
  const yr = (yaw * Math.PI) / 180
  const centre = usePath
    ? [(front[0] + rear[0]) / 2, (front[1] + rear[1]) / 2]
    : fromM([(-Math.cos(yr) * L) / 2, (-Math.sin(yr) * L) / 2], front)
  return {
    position: [centre[0], centre[1], z],
    yaw,
    pitch,
    signals: trip.signals?.at(lo) ?? 0,
    speed: trip.speeds?.at(lo) ?? 0,
    id: trip.vehicle_id,
    paint: trip.paint,
    model: trip.model,
  }
}

// A car is hidden only while it is under the tunnel roof (hidden_spans, from build_playback.py).
// On the open ramps it stays visible, although it is below street level.
const underRoof = (trip, t) => trip.hidden_spans?.some(([from, to]) => t >= from && t <= to)

export function vehicleStates(v, t) {
  const out = []
  for (const trip of v.trips) {
    const s = sample(trip, t)
    if (s && !underRoof(trip, t)) out.push(s)
  }
  return out
}

export function vehicleLayers(states, t, { visible = true } = {}) {
  const night = ENV.n
  // At night the scene light is dim, so the cars get more of their own color back, as if lit by
  // the street lamps; otherwise every car turns black
  const lift = 1 + night * 1.2
  const lit = (m) => ({ ...m, ambient: m.ambient * lift })
  const blink = Math.floor(t * 3) % 2 === 0 // indicators blink about 1.5 times a second
  const layers = []
  for (const model of CAR_MODELS) {
    const cars = states.filter((d) => d.model === model)
    const common = {
      getPosition: (d) => d.position,
      getOrientation: (d) => [d.pitch, d.yaw, 0],
      visible,
    }
    const layer = (part, data, props) =>
      new SimpleMeshLayer({
        id: `car-${model.name}-${part}`,
        data,
        mesh: model[part],
        ...common,
        getColor: [255, 255, 255],
        ...props,
      })
    layers.push(
      layer('paint', cars, { getColor: (d) => d.paint, material: lit(CARPAINT), pickable: true }),
      layer('shiny', cars, { material: lit(GLOSS) }),
      layer('matte', cars, { material: lit(MATTE) }),
      layer('head', cars, {
        getColor: night > 0.5 ? [255, 250, 232] : [236, 238, 232],
        material: glowMaterial(1 + night * 0.1),
      }),
      // tail lights are dark red in the day and turn on at night
      layer('tail', cars, {
        getColor: night > 0.5 ? [205, 26, 22] : [128, 20, 22],
        material: night > 0.5 ? glowMaterial() : lit(GLOSS),
      }),
      layer(
        'brake',
        cars.filter((d) => d.signals & 8),
        { getColor: [255, 40, 30], material: glowMaterial() },
      ),
      layer('indicatorLeft', blink ? cars.filter((d) => d.signals & 2) : [], {
        getColor: [255, 170, 20],
        material: glowMaterial(),
      }),
      layer('indicatorRight', blink ? cars.filter((d) => d.signals & 1) : [], {
        getColor: [255, 170, 20],
        material: glowMaterial(),
      }),
    )
  }
  return layers
}

// Keeps the vehicles of a run, one 15-minute file at a time (see run.json). at(t) gives the
// vehicles of the interval that contains t, or null while its file is still loading. It also
// starts loading the next interval of the analysis period (the first one again at its end), so
// the playback does not stop at the boundary.
//   run        run.json
//   loadFile   loads one vehicle file by its name, e.g. getVehicleInterval from the service
export function vehicleIntervals(run, loadFile) {
  const intervals = run.intervals
  const first = intervals.findIndex((interval) => interval.start_s >= run.analysis_start_s)
  const last = intervals.findLastIndex((interval) => interval.end_s <= run.analysis_end_s)
  const loaded = {}
  const requested = new Set()

  const request = (interval) => {
    if (requested.has(interval.file)) return
    requested.add(interval.file)
    loadFile(interval.file)
      .then((data) => (loaded[interval.file] = prepareVehicles(data)))
      .catch(() => (loaded[interval.file] = null)) // a missing file shows no cars for that interval
  }

  return {
    at(t) {
      const found = intervals.findIndex((interval) => t < interval.end_s)
      const i = found === -1 ? intervals.length - 1 : found
      request(intervals[i])
      request(intervals[i >= last ? first : i + 1])
      return loaded[intervals[i].file] ?? null
    },
  }
}
