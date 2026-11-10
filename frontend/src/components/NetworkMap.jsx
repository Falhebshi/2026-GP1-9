import { useEffect, useRef, useState } from 'react'
import { Map as MapLibreMap, NavigationControl, Popup } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { themeColor } from '../utils/theme'
import './NetworkMap.css'

// The city map on Network Traffic Overview: a light OpenFreeMap basemap (streets and district
// names from OpenStreetMap) drawn by MapLibre, with our road segments colored by congestion on
// top, or the same data as congestion by area (the Heatmap view).
//
//   bounds         [[west, south], [east, north]] the map opens on
//   maxBounds      the same shape: how far the map can be moved and zoomed out (optional; a
//                  margin around bounds if left out)
//   segments       GeoJSON road segments (see services/networkService.js), or null for none yet
//   view           'segments' or 'heatmap'
//   intersections  [{ id, name, area, center: [lon, lat], simulation }] shown as dots; the ones
//                  with a simulation pulse and can be clicked
//   selectedId     the intersection to highlight and fly to (or '' for none)
//   onSelect       called with an intersection id when its dot is clicked
//   onArrive       called with the id once the map has finished flying to it
//   padding        { top, right, bottom, left } in pixels: the space the page's floating cards
//                  take, so the map fits the study area (and its dots) into the part you can see
const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const EMPTY = { type: 'FeatureCollection', features: [] }

// Heatmap view. Every road adds its speed to a grid over the map area and the grid is blurred
// (Gaussian), giving a speed for every point of the city. Three looks are being compared; add
// ?heat=smooth, ?heat=fine or ?heat=hex to the page address to pick one:
//   smooth  a soft surface over the whole map (150 m grid, 600 m blur)
//   fine    a detailed surface (75 m grid, 150 m blur), clear where there is little road
//   hex     hexagon tiles of about 350 m in four colors (LOS A-B, C, D, E-F), only near roads
// Colors use the same level limits as the roads. It is for reading the city at a glance, not a
// measurement.
const HEAT_STYLES = {
  smooth: { cellLat: 0.00135, cellLon: 0.0015, sigma: 4, floor: 0.25, opacity: 0.75 },
  fine: { cellLat: 0.000675, cellLon: 0.00075, sigma: 2, floor: 0, opacity: 0.8 },
  hex: { cellLat: 0.00135, cellLon: 0.0015, sigma: 2 },
}
const HEX_RADIUS_M = 350
const TRANSPARENT =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='

function heatStyle() {
  const name = new URLSearchParams(window.location.search).get('heat')
  return HEAT_STYLES[name] ? name : 'smooth'
}

// [r, g, b] of a CSS color
function rgbOf(color) {
  const context = document.createElement('canvas').getContext('2d')
  context.fillStyle = color
  const hex = context.fillStyle // the browser turns any color into #rrggbb
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))
}

const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t))

// color of a speed (percent of free flow): green, yellow, orange, red, dark red
function heatColor(speed, stops) {
  for (let i = 1; i < stops.length; i++) {
    const [s0, c0] = stops[i - 1]
    const [s1, c1] = stops[i]
    if (speed >= s1) return mix(c0, c1, (s0 - speed) / (s0 - s1))
  }
  return stops.at(-1)[1]
}

// one-dimensional Gaussian blur of a grid (width x height), along rows or columns
function blur(values, width, height, sigma, alongRows) {
  const radius = Math.ceil(sigma * 3)
  const kernel = []
  for (let k = -radius; k <= radius; k++) kernel.push(Math.exp(-(k * k) / (2 * sigma * sigma)))
  const out = new Float32Array(values.length)
  for (let y = 0; y < height; y++)
    for (let x = 0; x < width; x++) {
      let sum = 0
      for (let k = -radius; k <= radius; k++) {
        const [xx, yy] = alongRows ? [x + k, y] : [x, y + k]
        if (xx < 0 || yy < 0 || xx >= width || yy >= height) continue
        sum += values[yy * width + xx] * kernel[k + radius]
      }
      out[y * width + x] = sum
    }
  return out
}

// The blurred speed of every grid cell over extent [[west, south], [east, north]]
function speedField(segments, extent, style) {
  const { cellLat, cellLon, sigma } = style
  const [[west, south], [east, north]] = extent
  const width = Math.ceil((east - west) / cellLon)
  const height = Math.ceil((north - south) / cellLat)
  const length = new Float32Array(width * height)
  const speedLength = new Float32Array(width * height)

  for (const f of segments.features) {
    const speed = f.properties.speed
    if (speed === null || speed === undefined) continue
    const line = f.geometry.coordinates
    for (let i = 1; i < line.length; i++) {
      const [a, b] = [line[i - 1], line[i]]
      const metres = Math.hypot((b[0] - a[0]) * 101000, (b[1] - a[1]) * 111000)
      const steps = Math.max(1, Math.round(metres / 20))
      for (let k = 0; k < steps; k++) {
        const t = (k + 0.5) / steps
        const x = Math.floor((a[0] + (b[0] - a[0]) * t - west) / cellLon)
        const y = Math.floor((north - (a[1] + (b[1] - a[1]) * t)) / cellLat)
        if (x < 0 || y < 0 || x >= width || y >= height) continue
        length[y * width + x] += metres / steps
        speedLength[y * width + x] += speed * (metres / steps)
      }
    }
  }

  const blurred = (grid) =>
    blur(blur(grid, width, height, sigma, true), width, height, sigma, false)
  const roads = blurred(length)
  const speeds = blurred(speedLength)

  // how much road counts as "a lot": the busiest tenth of the covered cells
  const covered = Array.from(roads)
    .filter((v) => v > 0)
    .sort((a, b) => a - b)
  const full = covered[Math.floor(covered.length * 0.9)] || 1

  return { width, height, roads, speeds, full, west, north, cellLat, cellLon }
}

// The smooth or fine surface, as a PNG data URL
function heatImage(segments, extent, colors, styleName) {
  const limits = segments?.limits
  if (!limits) return TRANSPARENT
  const style = HEAT_STYLES[styleName]
  const field = speedField(segments, extent, style)
  const { width, height, roads, speeds, full } = field
  const { low, moderate, high } = colors
  const stops = [
    [100, low],
    [limits.lowAboveSpeed, mix(low, moderate, 0.5)],
    [(limits.lowAboveSpeed + limits.moderateAboveSpeed) / 2, moderate],
    [limits.moderateAboveSpeed, high],
    [20, mix(high, [40, 0, 30], 0.5)],
  ]

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const context = canvas.getContext('2d')
  const image = context.createImageData(width, height)
  for (let i = 0; i < width * height; i++) {
    const speed = roads[i] > 1e-3 ? speeds[i] / roads[i] : 100
    const [r, g, b] = heatColor(speed, stops)
    // faint (or clear) where there is little road, full where there is a lot
    const strength = Math.min(roads[i] / full, 1)
    const alpha = style.floor + (1 - style.floor) * Math.sqrt(strength)
    image.data.set([r, g, b, Math.round(255 * alpha)], i * 4)
  }
  context.putImageData(image, 0, 0)
  return canvas.toDataURL()
}

// The hexagon tiles: four classes by speed (LOS A-B, C, D, E-F), only where there is road nearby
function hexagons(segments, extent) {
  const limits = segments?.limits
  if (!limits) return EMPTY
  const field = speedField(segments, extent, HEAT_STYLES.hex)
  const { width, height, roads, speeds, full, west, north, cellLat, cellLon } = field
  const [[, south], [east]] = extent
  const rLon = HEX_RADIUS_M / 101000
  const rLat = HEX_RADIUS_M / 111000
  const middle = (limits.lowAboveSpeed + limits.moderateAboveSpeed) / 2
  const features = []

  // pointy-top hexagons: rows 1.5 R apart, columns sqrt(3) R apart, every other row shifted
  for (let row = 0, lat = north; lat > south; row++, lat -= 1.5 * rLat) {
    const shift = row % 2 ? (Math.sqrt(3) * rLon) / 2 : 0
    for (let lon = west + shift; lon < east; lon += Math.sqrt(3) * rLon) {
      const x = Math.floor((lon - west) / cellLon)
      const y = Math.floor((north - lat) / cellLat)
      if (x < 0 || y < 0 || x >= width || y >= height) continue
      const i = y * width + x
      if (roads[i] < full * 0.08) continue
      const speed = speeds[i] / roads[i]
      const band =
        speed > limits.lowAboveSpeed
          ? 'low'
          : speed > middle
            ? 'fair'
            : speed > limits.moderateAboveSpeed
              ? 'moderate'
              : 'high'
      const ring = []
      for (let k = 0; k <= 6; k++) {
        const angle = (Math.PI / 180) * (60 * k - 30)
        ring.push([lon + rLon * Math.cos(angle), lat + rLat * Math.sin(angle)])
      }
      features.push({
        type: 'Feature',
        properties: { band },
        geometry: { type: 'Polygon', coordinates: [ring] },
      })
    }
  }
  return { type: 'FeatureCollection', features }
}

// content of the hover card (built from elements, not HTML text, so names are shown as typed)
function hoverContent(name, area, active) {
  const box = document.createElement('div')
  box.className = 'network-map-hover-body'
  const line = (tag, className, text) => {
    const el = document.createElement(tag)
    el.className = className
    el.textContent = text
    box.appendChild(el)
  }
  line('strong', 'network-map-hover-name', name)
  line('span', 'network-map-hover-area', area)
  line(
    'span',
    active
      ? 'network-map-hover-status network-map-hover-status-active'
      : 'network-map-hover-status',
    active ? 'Click to open the simulation' : 'Simulation not available yet',
  )
  return box
}

function NetworkMap({
  bounds,
  maxBounds,
  segments,
  view = 'segments',
  intersections = [],
  selectedId,
  onSelect,
  onArrive,
  padding,
}) {
  const containerRef = useRef(null)
  const mapRef = useRef(null)
  const onSelectRef = useRef(onSelect)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  const onArriveRef = useRef(onArrive)

  useEffect(() => {
    onSelectRef.current = onSelect
    onArriveRef.current = onArrive
  }, [onSelect, onArrive])

  // the area the map can show, which the heat image covers
  const extent = maxBounds ?? [
    [bounds[0][0] - 0.12, bounds[0][1] - 0.1],
    [bounds[1][0] + 0.12, bounds[1][1] + 0.1],
  ]
  const extentRef = useRef(extent)
  extentRef.current = extent
  const colorsRef = useRef(null)

  // create the map once
  useEffect(() => {
    const map = new MapLibreMap({
      container: containerRef.current,
      style: STYLE_URL,
      bounds,
      // leave room at the bottom for the timeline card that sits over the map
      fitBoundsOptions: { padding: { top: 20, right: 20, left: 20, bottom: 200 } },
      minZoom: 10,
      maxBounds: extent,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    })
    map.touchZoomRotate.disableRotation()
    map.addControl(new NavigationControl({ showCompass: false }), 'bottom-right')
    mapRef.current = map

    let loaded = false
    let frame = 0
    map.on('error', (event) => {
      // the basemap style itself couldn't load (offline, or the server is down). Errors from
      // single tiles come with a sourceId and don't stop the map, so they're ignored.
      if (!loaded && !event.sourceId) setFailed(true)
    })

    map.on('load', () => {
      loaded = true
      // The map credits (required by the OpenStreetMap licence) start folded into the small (i)
      // button; clicking it shows them.
      containerRef.current
        .querySelector('.maplibregl-ctrl-attrib')
        ?.classList.remove('maplibregl-compact-show')
      // congestion colors from the theme (index.css), so the map matches the legend
      const low = themeColor('--congestion-low')
      const moderate = themeColor('--congestion-moderate')
      const high = themeColor('--congestion-high')
      const none = themeColor('--congestion-none')
      const selected = themeColor('--color-selected')

      // draw our layers under the basemap's place names, so district names stay readable
      const firstLabel = map.getStyle().layers.find((l) => l.type === 'symbol')?.id

      map.addSource('segments', { type: 'geojson', data: EMPTY })
      colorsRef.current = { low: rgbOf(low), moderate: rgbOf(moderate), high: rgbOf(high) }
      const yellow = `rgb(${mix(rgbOf(moderate), [255, 221, 87], 0.6).join(',')})`
      map.addSource('heat-hex', { type: 'geojson', data: EMPTY })
      const [[w, s], [e, n]] = extentRef.current
      map.addSource('heat', {
        type: 'image',
        url: TRANSPARENT,
        coordinates: [
          [w, n],
          [e, n],
          [e, s],
          [w, s],
        ],
      })
      map.addSource('intersections', { type: 'geojson', data: EMPTY })

      map.addLayer(
        {
          id: 'segments',
          type: 'line',
          source: 'segments',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
            'line-color': [
              'match',
              ['get', 'level'],
              'low',
              low,
              'moderate',
              moderate,
              'high',
              high,
              none,
            ],
            'line-width': ['interpolate', ['linear'], ['zoom'], 11, 2, 14, 4, 17, 8],
            'line-opacity': 0.9,
          },
        },
        firstLabel,
      )
      map.addLayer(
        {
          id: 'heat',
          type: 'raster',
          source: 'heat',
          layout: { visibility: 'none' },
          paint: {
            'raster-opacity': HEAT_STYLES[heatStyle()].opacity ?? 0.75,
            'raster-resampling': 'linear', // smooth between the grid's pixels
            'raster-fade-duration': 0,
          },
        },
        firstLabel,
      )
      map.addLayer(
        {
          id: 'heat-hex',
          type: 'fill',
          source: 'heat-hex',
          layout: { visibility: 'none' },
          paint: {
            'fill-color': [
              'match',
              ['get', 'band'],
              'low',
              low,
              'fair',
              yellow,
              'moderate',
              moderate,
              high,
            ],
            'fill-opacity': 0.55,
            'fill-outline-color': 'rgba(255,255,255,0.8)',
          },
        },
        firstLabel,
      )
      // a ring that keeps growing and fading around the intersections you can open
      map.addLayer({
        id: 'intersections-pulse',
        type: 'circle',
        source: 'intersections',
        filter: ['get', 'active'],
        paint: {
          'circle-radius': 7,
          'circle-color': selected,
          'circle-opacity': 0,
          'circle-stroke-width': 0,
        },
      })
      map.addLayer({
        id: 'intersections',
        type: 'circle',
        source: 'intersections',
        paint: {
          'circle-radius': ['case', ['get', 'selected'], 9, 7],
          'circle-color': selected,
          'circle-stroke-color': themeColor('--color-surface'),
          'circle-stroke-width': 2,
        },
      })
      // a larger invisible circle around each dot, so it is easy to click and hover
      map.addLayer({
        id: 'intersections-hit',
        type: 'circle',
        source: 'intersections',
        paint: { 'circle-radius': 16, 'circle-opacity': 0 },
      })
      const pulse = (now) => {
        const t = (now % 1600) / 1600 // one pulse every 1.6 s
        map.setPaintProperty('intersections-pulse', 'circle-radius', 7 + 16 * t)
        map.setPaintProperty('intersections-pulse', 'circle-opacity', 0.45 * (1 - t))
        frame = requestAnimationFrame(pulse)
      }
      frame = requestAnimationFrame(pulse)
      // small card with the intersection's name and district while the mouse is on its dot
      const hoverCard = new Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 14,
        className: 'network-map-hover',
      })
      // mousemove rather than mouseenter, so moving straight from one dot to the next updates it
      // after a click the map zooms in; the card stays hidden until the zoom has finished
      let zooming = false
      map.on('click', 'intersections-hit', (event) => {
        const props = event.features?.[0]?.properties
        if (!props?.active) return
        hoverCard.remove()
        zooming = true
        map.once('moveend', () => {
          zooming = false
        })
        onSelectRef.current?.(props.id)
      })
      map.on('mousemove', 'intersections-hit', (event) => {
        const feature = event.features?.[0]
        if (!feature || zooming) return
        const { name, area, active } = feature.properties
        if (active) map.getCanvas().style.cursor = 'pointer'
        hoverCard
          .setLngLat(feature.geometry.coordinates)
          .setDOMContent(hoverContent(name, area, active))
          .addTo(map)
      })
      map.on('mouseleave', 'intersections-hit', () => {
        map.getCanvas().style.cursor = ''
        hoverCard.remove()
      })
      setReady(true)
    })

    return () => {
      cancelAnimationFrame(frame)
      map.remove()
      mapRef.current = null
      setReady(false) // a new map (after a hot reload) has to load its layers again
    }
  }, [bounds, maxBounds])

  // segment data
  useEffect(() => {
    if (!ready) return
    const map = mapRef.current
    map.getSource('segments').setData(segments ?? EMPTY)
    const [[w, s], [e, n]] = extentRef.current
    if (heatStyle() === 'hex') {
      map.getSource('heat-hex').setData(hexagons(segments, extentRef.current))
      return
    }
    map.getSource('heat').updateImage({
      url: heatImage(segments, extentRef.current, colorsRef.current, heatStyle()),
      coordinates: [
        [w, n],
        [e, n],
        [e, s],
        [w, s],
      ],
    })
  }, [ready, segments])

  // segments or heatmap
  useEffect(() => {
    if (!ready) return
    const map = mapRef.current
    map.setLayoutProperty('segments', 'visibility', view === 'segments' ? 'visible' : 'none')
    const hex = heatStyle() === 'hex'
    const shown = (on) => (view === 'heatmap' && on ? 'visible' : 'none')
    map.setLayoutProperty('heat', 'visibility', shown(!hex))
    map.setLayoutProperty('heat-hex', 'visibility', shown(hex))
  }, [ready, view])

  // Fit the study area into the part of the map the floating cards leave free, again whenever
  // they change size (a smaller window makes the timeline card taller). Not while an
  // intersection is selected, so it doesn't undo the zoom to it.
  const paddingKey = padding
    ? `${padding.top},${padding.right},${padding.bottom},${padding.left}`
    : ''
  useEffect(() => {
    if (!ready || !padding || selectedId) return
    const map = mapRef.current
    const { width, height } = map.getContainer().getBoundingClientRect()
    // when the cards leave almost no room, use what is left rather than failing to fit
    const fits =
      width - padding.left - padding.right > 80 && height - padding.top - padding.bottom > 80
    map.fitBounds(bounds, { padding: fits ? padding : 20, duration: 0 })
  }, [ready, paddingKey, bounds]) // eslint-disable-line react-hooks/exhaustive-deps

  // intersection dots, and fly to the selected one
  useEffect(() => {
    if (!ready) return
    const map = mapRef.current
    map.getSource('intersections').setData({
      type: 'FeatureCollection',
      features: intersections.map((i) => ({
        type: 'Feature',
        properties: {
          id: i.id,
          name: i.name,
          area: i.area,
          active: Boolean(i.simulation),
          selected: i.id === selectedId,
        },
        geometry: { type: 'Point', coordinates: i.center },
      })),
    })
    const chosen = intersections.find((i) => i.id === selectedId)
    if (!chosen) return
    map.flyTo({ center: chosen.center, zoom: 16.5, duration: 2200, essential: true })
    map.once('moveend', () => onArriveRef.current?.(chosen.id))
  }, [ready, intersections, selectedId])

  return (
    <div className="network-map">
      <div ref={containerRef} className="network-map-canvas" />
      {failed && (
        <div className="network-map-message">
          The map couldn't load. Check your internet connection and refresh the page.
        </div>
      )}
    </div>
  )
}

export default NetworkMap
