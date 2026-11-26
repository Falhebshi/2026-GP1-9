// The speed a road segment is drawn with on Network Traffic Overview.
//
// The server gives every segment its own speed: each road (corridor) is ranked on its own by the
// trip model, so a short piece or a ramp that the model routed few trips through can come out
// green between two red roads. On the map that reads as a gap in the congestion that nothing on
// the ground explains. So, for drawing only, a short piece (under SHORT_M) or a ramp (is_link) is
// kept between the speeds of the roads at its two ends:
//
//   faster than both ends  -> drawn at the faster end's speed
//   slower than both ends  -> drawn at the slower end's speed
//   in between             -> its own speed
//
// A real step from red to green along a road is kept (the piece in between stays in between),
// longer segments keep their own speed, and the stored speeds and the timeline are not changed.
// The road at an end is the one the segment continues from or into (the smallest change of
// direction, under MAX_TURN_DEG); for a ramp, the main road at each end of the whole ramp.

const SHORT_M = 200
const MAX_TURN_DEG = 60
// Some ramps in OpenStreetMap stop short of the road they join (their last stretch is a smaller
// road the map doesn't hold), so a ramp end may be up to GAP_M from the road's end point.
const GAP_M = 50

const keyOf = (p) => `${p[0].toFixed(5)},${p[1].toFixed(5)}`
const metres = (a, b) => Math.hypot((b[0] - a[0]) * 101000, (b[1] - a[1]) * 110540)
const lengthOf = (line) => line.slice(1).reduce((sum, p, i) => sum + metres(line[i], p), 0)
const bearing = (a, b) => (Math.atan2((b[1] - a[1]) * 110540, (b[0] - a[0]) * 101000) * 180) / Math.PI
const turnBetween = (a, b) => Math.abs(((a - b + 540) % 360) - 180)

// Once per segment list: for every segment, the index of the road at its start and at its end
// ([-1, -1] when it keeps its own speed).
export function segmentEnds(features) {
  const lines = features.map((f) => f.geometry.coordinates)
  const startsAt = new Map()
  const endsAt = new Map()
  lines.forEach((line, i) => {
    const s = keyOf(line[0])
    const e = keyOf(line.at(-1))
    if (!startsAt.has(s)) startsAt.set(s, [])
    if (!endsAt.has(e)) endsAt.set(e, [])
    startsAt.get(s).push(i)
    endsAt.get(e).push(i)
  })
  // end points on a grid of about 50 m, to find the nearby ones
  const cellOf = (p) => [Math.floor(p[0] * 2000), Math.floor(p[1] * 2000)]
  const grid = { starts: new Map(), ends: new Map() }
  lines.forEach((line, i) => {
    for (const [which, p] of [['starts', line[0]], ['ends', line.at(-1)]]) {
      const k = cellOf(p).join(',')
      if (!grid[which].has(k)) grid[which].set(k, [])
      grid[which].get(k).push(i)
    }
  })
  const nearby = (p, which) => {
    const [cx, cy] = cellOf(p)
    const out = []
    for (let x = cx - 1; x <= cx + 1; x++)
      for (let y = cy - 1; y <= cy + 1; y++)
        for (const j of grid[which].get(`${x},${y}`) ?? []) {
          const q = which === 'starts' ? lines[j][0] : lines[j].at(-1)
          if (metres(p, q) <= GAP_M) out.push(j)
        }
    return out
  }
  const isLink = (i) => Boolean(features[i].properties.is_link)
  // the other direction of the same two-way road
  const isReverse = (a, b) => keyOf(a[0]) === keyOf(b.at(-1)) && keyOf(a.at(-1)) === keyOf(b[0])

  // the segment before (back) or after this one with the smallest change of direction
  const continued = (i, back) => {
    const line = lines[i]
    const candidates = (back ? endsAt.get(keyOf(line[0])) : startsAt.get(keyOf(line.at(-1)))) ?? []
    const heading = back ? bearing(line[0], line[1]) : bearing(line.at(-2), line.at(-1))
    let pick = -1
    let smallest = MAX_TURN_DEG
    for (const j of candidates) {
      if (j === i || isReverse(lines[j], line)) continue
      const other = lines[j]
      const h = back ? bearing(other.at(-2), other.at(-1)) : bearing(other[0], other[1])
      const turn = turnBetween(h, heading)
      if (turn < smallest) {
        smallest = turn
        pick = j
      }
    }
    return pick
  }

  // the segments joined to this one's start (back) or end, nearby ones for a ramp that stops short
  const joined = (i, back) => {
    const line = lines[i]
    const exact = (back ? endsAt.get(keyOf(line[0])) : startsAt.get(keyOf(line.at(-1)))) ?? []
    const found = exact.filter((j) => j !== i && !isReverse(lines[j], line))
    if (found.length) return found
    return (back ? nearby(line[0], 'ends') : nearby(line.at(-1), 'starts')).filter((j) => j !== i)
  }

  // a ramp: the first main road reached going back (or forward) along the ramp's pieces, trying
  // every branch, since ramps split, merge and loop at interchanges
  const mainRoadAt = (i, back) => {
    const seen = new Set([i])
    let level = [i]
    for (let step = 0; step < 30 && level.length; step++) {
      const next = []
      for (const j of level)
        for (const k of joined(j, back)) {
          if (seen.has(k)) continue
          seen.add(k)
          if (!isLink(k)) return k
          next.push(k)
        }
      level = next
    }
    return -1
  }

  return lines.map((line, i) => {
    if (isLink(i)) return [mainRoadAt(i, true), mainRoadAt(i, false)]
    if (lengthOf(line) < SHORT_M) return [continued(i, true), continued(i, false)]
    return [-1, -1]
  })
}

// speeds: one per segment (percent of free flow, or null); ends: from segmentEnds
export function drawnSpeeds(speeds, ends) {
  return speeds.map((speed, i) => {
    const [before, after] = ends[i]
    if (speed === null || before < 0 || after < 0) return speed
    const a = speeds[before]
    const b = speeds[after]
    if (a === null || b === null) return speed
    return Math.min(Math.max(speed, Math.min(a, b)), Math.max(a, b))
  })
}
