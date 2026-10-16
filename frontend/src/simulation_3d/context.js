import { SolidPolygonLayer, PathLayer } from '@deck.gl/layers'
import { PALETTE } from './palette'
import { material } from './materials'

// Background map from OpenStreetMap (parking, green areas, land use and streets that are not in the SUMO network).
// It's only for looks and is drawn flat under the simulated roads. Built by data/sumo_run/build_context.py.
const AREA_ORDER = { campus: 0, landuse: 0, parking: 1, pitch: 1, green: 1, water: 2 }

export function prepareContext(geojson) {
  const areas = geojson.features
    .filter((f) => f.properties.kind === 'area')
    .sort((a, b) => AREA_ORDER[a.properties.class] - AREA_ORDER[b.properties.class])
  const lines = geojson.features.filter((f) => f.properties.kind === 'line')
  // Draw wider streets first so the narrow paths end up on top.
  lines.sort((a, b) => b.properties.width_m - a.properties.width_m)
  return { areas, lines }
}

// "light" draws the nearby streets, parking, green areas and sports pitches. "full" also adds
// aisles, footpaths and campus areas. `parameters` is the same street-level draw order that roadLayers uses.
const LEVEL = 'light'

export function contextLayers(ctx, { visible = true, parameters, level = LEVEL } = {}) {
  const C = PALETTE.context
  if (level === 'light')
    ctx = {
      areas: ctx.areas.filter((f) => ['parking', 'green', 'pitch'].includes(f.properties.class)),
      lines: ctx.lines.filter((f) => f.properties.class === 'street'),
    }
  return [
    // Parking lots get the light asphalt texture, other areas use a flat color.
    new SolidPolygonLayer({
      id: 'context-parking',
      data: ctx.areas.filter((f) => f.properties.class === 'parking'),
      visible,
      parameters,
      getPolygon: (f) => f.geometry.coordinates,
      ...material('parking'),
    }),
    new SolidPolygonLayer({
      id: 'context-areas',
      data: ctx.areas.filter((f) => f.properties.class !== 'parking'),
      visible,
      parameters,
      getPolygon: (f) => f.geometry.coordinates,
      getFillColor: (f) => C[f.properties.class],
    }),
    // A slightly wider light line under each street to show the road edge.
    new PathLayer({
      id: 'context-casing',
      data: ctx.lines.filter((f) => f.properties.class !== 'path'),
      visible,
      parameters,
      getPath: (f) => f.geometry.coordinates,
      widthUnits: 'meters',
      getWidth: (f) => f.properties.width_m + 0.8,
      capRounded: true,
      jointRounded: true,
      getColor: C.casing,
    }),
    new PathLayer({
      id: 'context-lines',
      data: ctx.lines,
      visible,
      parameters,
      getPath: (f) => f.geometry.coordinates,
      widthUnits: 'meters',
      getWidth: (f) => f.properties.width_m,
      widthMinPixels: 0.5,
      capRounded: true,
      jointRounded: true,
      getColor: (f) => C[f.properties.class],
    }),
  ]
}
