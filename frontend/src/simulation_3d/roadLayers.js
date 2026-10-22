import { SolidPolygonLayer, PathLayer, IconLayer } from '@deck.gl/layers'
import { SimpleMeshLayer } from '@deck.gl/mesh-layers'
import { dashLine, offsetPath, toM, fromM } from './geo'
import { LAMP_POLE, LAMP_LENS } from './meshes'
import { material, variation } from './materials'
import { PALETTE, glowMaterial } from './palette'
import { contextLayers } from './context'
import { streetscapeLayers } from './streetscape'

// Everything below street level is drawn first with a normal depth test. The street level layers all
// lie in the same flat plane, so they skip the depth test and are drawn in order, one on top of the other.
// They still write depth, so the underpass only shows through the open ramps.
const STREET = { depthCompare: 'always', depthWriteEnabled: true }
const GROUND_DROP = 0
const FLOOR_DROP = 0.35
const deepen = (f, dh) => ({
  ...f,
  properties: { ...f.properties, height_m: f.properties.height_m + dh },
})
const shiftRings = (f, dz) => ({
  ...f,
  geometry: {
    ...f.geometry,
    coordinates: f.geometry.coordinates.map((r) => r.map(([x, y, z = 0]) => [x, y, z + dz])),
  },
})

const LAMP_SPACING_M = 60 // distance between street lamps along each road, in metres
const LAMP_POOL_M = 58 // diameter of the light pool under each lamp, in metres
// Round glow image for the lamp pools. Warm in the middle and fading out to the edge.
const GLOW_MAPPING = { glow: { x: 0, y: 0, width: 256, height: 256, mask: false } }
let GLOW_CANVAS = null
function glowSprite() {
  if (GLOW_CANVAS) return GLOW_CANVAS
  const c = document.createElement('canvas')
  c.width = c.height = 256
  const g = c.getContext('2d'),
    grad = g.createRadialGradient(128, 128, 0, 128, 128, 128)
  // Smooth falloff with many stops so no ring shows. It reaches zero before the edge of the image.
  for (let i = 0; i <= 16; i++) {
    const r = i / 16,
      a = 0.3 * Math.exp(-((r / 0.42) ** 2)) * (1 - r)
    grad.addColorStop(
      r,
      `rgba(255, ${Math.round(205 - 20 * r)}, ${Math.round(150 - 35 * r)}, ${a.toFixed(4)})`,
    )
  }
  g.fillStyle = grad
  g.fillRect(0, 0, 256, 256)
  return (GLOW_CANVAS = c)
}

export function prepareNetwork({ surface, markings, arrows, underpass, detail = null }) {
  const lanes = [],
    internal = [],
    junctions = [],
    underground = []
  for (const f of surface.features) {
    const p = f.properties
    if (p.level === 'underground') underground.push(f)
    else if (p.kind === 'junction') junctions.push(f)
    else if (p.internal) internal.push(f)
    else lanes.push(f)
  }
  const strokes = [],
    strokesUnder = []
  // all dashed lines line up their dashes from the same point (any point works, as long as it's
  // the same for every line)
  const dashOrigin = markings.features[0]?.geometry.coordinates[0]
  for (const f of markings.features) {
    const p = f.properties
    const color = PALETTE.paint[p.color] ?? PALETTE.paint.white
    const below = f.geometry.coordinates.some((c) => (c[2] ?? 0) < -0.05)
    const pieces =
      p.pattern === 'broken'
        ? dashLine(f.geometry.coordinates, p.dash_m, p.gap_m, dashOrigin)
        : [f.geometry.coordinates]
    for (const path of pieces)
      (below ? strokesUnder : strokes).push({ path, color, width: p.width_m })
  }
  const byKind = (k) => underpass.features.filter((f) => f.properties.kind === k)
  const aprons = (detail?.features ?? []).filter((f) => f.properties.kind === 'apron')
  const roadOutline = (detail?.features ?? []).filter((f) => f.properties.kind === 'road_outline')
  // OSM says these roads are lit but doesn't give lamp positions, so we place a 10 m pole every 60 m
  // on the median side of each road. This is the usual layout on Riyadh main roads, not real positions.
  const lamps = []
  const byEdge = {}
  for (const f of detail?.features ?? []) {
    const p = f.properties
    if (p.kind !== 'lane_centre' || p.internal) continue
    if (f.geometry.coordinates.some((q) => (q[2] ?? 0) < -0.3)) continue
    const [edge, idx] = [
      p.lane.slice(0, p.lane.lastIndexOf('_')),
      Number(p.lane.slice(p.lane.lastIndexOf('_') + 1)),
    ]
    if (!byEdge[edge] || idx > byEdge[edge].idx) byEdge[edge] = { idx, f }
  }
  for (const { f } of Object.values(byEdge)) {
    const c = f.geometry.coordinates,
      o = c[0]
    const side = offsetPath(c, f.properties.width / 2 + 1.0)
    const P = side.map((q) => toM(q, o))
    let run = 0,
      next = 25
    for (let i = 1; i < P.length; i++) {
      const seg = Math.hypot(P.at(i)[0] - P.at(i - 1)[0], P.at(i)[1] - P.at(i - 1)[1])
      while (next <= run + seg) {
        const k = (next - run) / seg,
          x = P.at(i - 1)[0] + (P.at(i)[0] - P.at(i - 1)[0]) * k,
          y = P.at(i - 1)[1] + (P.at(i)[1] - P.at(i - 1)[1]) * k
        // the arm points at the road, which is on the right of the lamp row's direction
        const dx = P.at(i)[0] - P.at(i - 1)[0],
          dy = P.at(i)[1] - P.at(i - 1)[1]
        lamps.push({ position: fromM([x, y], o), yaw: (Math.atan2(-dx, dy) * 180) / Math.PI })
        next += LAMP_SPACING_M
      }
      run += seg
    }
  }
  return {
    aprons,
    roadOutline,
    lamps,
    lanes,
    internal,
    junctions,
    underground,
    strokes,
    arrows: arrows.features,
    ground: byKind('ground').map((f) => shiftRings(f, GROUND_DROP)),
    roof: byKind('roof'),
    roofSlats: byKind('roof_slat'),
    // Keep the underground surfaces apart in height so they don't flicker against each other.
    // The ramp floor sits 35 cm under the underpass lanes.
    rampFloor: byKind('ramp_floor').map((f) => shiftRings(f, -FLOOR_DROP)),
    walls: byKind('wall').map((f) => deepen(shiftRings(f, -FLOOR_DROP), FLOOR_DROP)),
    beams: byKind('portal_beam'),
    strokesUnder: strokesUnder.map((d) => ({
      ...d,
      path: d.path.map(([x, y, z = 0]) => [x, y, z + 0.02]),
    })),
  }
}

export function roadLayers(
  net,
  {
    selectedIds = null,
    xray = false,
    paintOpacity = 1,
    slatOpacity = 1,
    night = 0,
    context = null,
    showContext = true,
    streetscape = null,
    show3d = true,
  } = {},
) {
  const ring = (f) => f.geometry.coordinates[0]
  const rings = (f) => f.geometry.coordinates // polygon with holes
  const paint = (id, data, extra = {}) =>
    new PathLayer({
      id,
      data,
      getPath: (d) => d.path,
      getColor: (d) => d.color,
      widthUnits: 'meters',
      getWidth: (d) => d.width,
      jointRounded: true,
      capRounded: true,
      opacity: paintOpacity * (0.9 - 0.25 * night),
      visible: paintOpacity > 0.02,
      ...extra,
    })
  // Additive blending for the lamp pools, so they brighten whatever is under them like real light.
  const ADD = {
    depthCompare: 'always',
    depthWriteEnabled: false,
    blend: true,
    blendColorOperation: 'add',
    blendColorSrcFactor: 'src-alpha',
    blendColorDstFactor: 'one',
    blendAlphaOperation: 'add',
    blendAlphaSrcFactor: 'one',
    blendAlphaDstFactor: 'one',
  }
  // Flat street level layers would only shadow themselves, so leave them out of the shadow pass.
  const flat = (layer) =>
    layer.props.parameters === STREET ? layer.clone({ shadowEnabled: false }) : layer
  return [
    // Below street level. The texture doesn't render on these sloped polygons, so they use plain colors.
    new SolidPolygonLayer({
      id: 'ramp-floor',
      data: net.rampFloor,
      getPolygon: ring,
      // same asphalt grey as the lanes: there are small gaps between SUMO's lane strips, and a
      // lighter floor showed through them as grey lines
      getFillColor: [64, 65, 68],
      material: false,
    }),
    new SolidPolygonLayer({
      id: 'underpass-lanes',
      data: net.underground,
      getPolygon: ring,
      // same asphalt grey as the street (the textured street asphalt isn't lit, so this isn't either)
      getFillColor: [64, 65, 68],
      material: false,
    }),
    paint('underpass-paint', net.strokesUnder),
    new SolidPolygonLayer({
      id: 'ramp-walls',
      data: net.walls,
      getPolygon: ring,
      extruded: true,
      getElevation: (f) => f.properties.height_m,
      getFillColor: PALETTE.concrete,
    }),
    new SolidPolygonLayer({
      id: 'portal-beams',
      data: net.beams,
      getPolygon: ring,
      extruded: true,
      getElevation: (f) => f.properties.height_m,
      getFillColor: PALETTE.concrete,
    }),
    // Darken the underpass at night (it shows through the open ramps). Drawn here with the other
    // below-street layers, so the street surface is always painted over it.
    new SolidPolygonLayer({
      id: 'night-veil-underpass',
      data: [...net.rampFloor, ...net.underground],
      getPolygon: ring,
      visible: night > 0.01 && !xray,
      getFillColor: [6, 10, 24, Math.round(205 * night)],
      parameters: { depthCompare: 'less-equal', depthWriteEnabled: false },
      updateTriggers: { getFillColor: night },
    }),
    // Street level, drawn in order: ground, tunnel roof, road, then paint.
    // The open land around the roads is desert sand. The ground has holes over the open ramps.
    new SolidPolygonLayer({
      id: 'ground',
      data: net.ground,
      getPolygon: rings,
      ...(xray ? { getFillColor: [...PALETTE.ground, 110] } : material('sand')),
      parameters: xray ? { depthCompare: 'always', depthWriteEnabled: false } : STREET,
      updateTriggers: { getFillColor: xray },
    }),
    // Soft, large patches over the open ground so it isn't one flat color: slightly darker
    // earth, paler compacted ground and a faint dry-scrub tint. Low strength and different sizes
    // and positions, so nothing lines up or looks like a pattern.
    ...[
      ['ground-variation', [150, 140, 122, 80], 1, [0, 0]],
      ['ground-pale', [216, 210, 196, 85], 1.7, [0.62, 0.81]],
      ['ground-scrub', [150, 152, 126, 62], 0.7, [0.21, 0.47]],
    ].map(
      ([id, color, scale, offset]) =>
        new SolidPolygonLayer({
          id,
          data: net.ground,
          getPolygon: rings,
          visible: !xray,
          ...variation(color, { scale, offset }),
          parameters: STREET,
        }),
    ),
    // Paved area around the buildings, roughly 3 m wide.
    new SolidPolygonLayer({
      id: 'aprons',
      data: net.aprons,
      getPolygon: rings,
      visible: !xray,
      ...material('apron'),
      parameters: STREET,
    }),
    // Background map (parking, streets we don't simulate), drawn under the simulated roads.
    ...(context
      ? contextLayers(context, { visible: showContext && !xray, parameters: STREET })
      : []),
    // Slatted roof over the covered underpass, as seen on satellite images. The slats fade out when
    // zoomed out because the 0.7 m stripes would flicker on screen.
    new SolidPolygonLayer({
      id: 'tunnel-roof',
      data: net.roof,
      getPolygon: ring,
      getFillColor: PALETTE.roof,
      parameters: STREET,
      visible: !xray,
      shadowEnabled: false,
    }),
    new SolidPolygonLayer({
      id: 'tunnel-roof-slats',
      data: net.roofSlats,
      getPolygon: ring,
      ...material('slab'),
      opacity: slatOpacity,
      parameters: STREET,
      visible: !xray && slatOpacity > 0.02,
    }),
    // Road surface: one even asphalt for junctions and lanes, then the paint.
    new SolidPolygonLayer({
      id: 'junctions',
      data: net.junctions,
      getPolygon: ring,
      parameters: STREET,
      ...material('asphalt'),
    }),
    new SolidPolygonLayer({
      id: 'junction-lanes',
      data: net.internal,
      getPolygon: ring,
      parameters: STREET,
      ...material('asphalt'),
    }),
    new SolidPolygonLayer({
      id: 'lanes',
      data: net.lanes,
      getPolygon: ring,
      pickable: true,
      parameters: STREET,
      ...material('asphalt'),
    }),
    // Textured surfaces ignore scene lighting, so at night we cover the street level with a dark blue
    // layer and then add the lamp light back on top.
    new SolidPolygonLayer({
      id: 'night-veil',
      data: net.ground,
      getPolygon: rings,
      visible: night > 0.01,
      getFillColor: [6, 10, 24, Math.round(205 * night)],
      parameters: STREET,
      updateTriggers: { getFillColor: night },
    }),
    // A warm pool of light under every lamp. Neighbouring pools overlap so the whole road looks lit.
    new IconLayer({
      id: 'lamp-pools',
      data: net.lamps,
      visible: night > 0.01 && !xray,
      billboard: false,
      iconAtlas: glowSprite(),
      iconMapping: GLOW_MAPPING,
      getIcon: () => 'glow',
      getPosition: (d) => [...d.position, 0.02],
      sizeUnits: 'meters',
      getSize: LAMP_POOL_M,
      getColor: [255, 255, 255, 255],
      opacity: night,
      parameters: ADD,
      alphaCutoff: 0,
    }), // cutoff 0 keeps the faint edge of the glow so the pools have no hard border
    new SolidPolygonLayer({
      id: 'road-lighting',
      data: net.roadOutline,
      getPolygon: rings,
      visible: night > 0.01 && !xray,
      getFillColor: [255, 200, 140, Math.round(14 * night)],
      parameters: ADD,
      updateTriggers: { getFillColor: night },
    }),
    // The clicked lane gets a blue tint. It's drawn under the paint so the markings stay visible.
    new SolidPolygonLayer({
      id: 'lane-selected',
      data: selectedIds ? net.lanes.filter((f) => selectedIds.has(f.properties.id)) : [],
      getPolygon: ring,
      getFillColor: [37, 99, 235, 150],
      parameters: STREET,
    }),
    paint('paint', net.strokes, { parameters: STREET }),
    new SolidPolygonLayer({
      id: 'arrows',
      data: net.arrows,
      getPolygon: ring,
      getFillColor: [...PALETTE.paint.white, 235],
      opacity: paintOpacity * (1 - 0.3 * night),
      visible: paintOpacity > 0.02,
      parameters: STREET,
    }),
    // Kerbs, sidewalks and medians stand up from the road, so they use the normal depth test.
    ...(streetscape ? streetscapeLayers(streetscape, { visible: show3d && !xray, night }) : []),
    // Street lamps: grey poles with heads that glow at night.
    new SimpleMeshLayer({
      id: 'lamp-poles',
      data: net.lamps,
      visible: !xray,
      mesh: LAMP_POLE,
      getPosition: (d) => d.position,
      getOrientation: (d) => [0, d.yaw, 0],
      getColor: [255, 255, 255],
      material: { ambient: 0.45, diffuse: 0.55, shininess: 30, specularColor: [70, 70, 70] },
    }),
    new SimpleMeshLayer({
      id: 'lamp-heads',
      data: net.lamps,
      visible: !xray,
      mesh: LAMP_LENS,
      getPosition: (d) => d.position,
      getOrientation: (d) => [0, d.yaw, 0],
      getColor: night > 0.4 ? [255, 222, 176] : [196, 200, 204],
      material: night > 0.4 ? glowMaterial() : undefined,
      updateTriggers: { getColor: night > 0.4 },
    }),
  ].map(flat)
}
