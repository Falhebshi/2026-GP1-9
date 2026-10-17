import { useEffect, useRef, useState } from 'react'
import { Map as MapLibreMap, NavigationControl, Popup } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { themeColor } from '../utils/theme'
import './NetworkMap.css'

// The city map on Network Traffic Overview: a light OpenFreeMap basemap (streets and district
// names from OpenStreetMap) drawn by MapLibre, with our road segments colored by congestion on
// top, or a heatmap of the same data.
//
//   bounds         [[west, south], [east, north]] the map opens on
//   segments       GeoJSON road segments (see services/networkService.js), or null for none yet
//   view           'segments' or 'heatmap'
//   intersections  [{ id, name, area, center: [lon, lat], simulation }] shown as dots; the ones
//                  with a simulation pulse and can be clicked
//   selectedId     the intersection to highlight and fly to (or '' for none)
//   onSelect       called with an intersection id when its dot is clicked
//   onArrive       called with the id once the map has finished flying to it
const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const EMPTY = { type: 'FeatureCollection', features: [] }


// Points every ~40 m along the segments, carrying the segment's congestion, for the heatmap.
function heatPoints(segments) {
  const features = []
  for (const f of segments?.features ?? []) {
    const lines =
      f.geometry.type === 'MultiLineString' ? f.geometry.coordinates : [f.geometry.coordinates]
    for (const line of lines)
      for (let i = 1; i < line.length; i++) {
        const [a, b] = [line[i - 1], line[i]]
        const metres = Math.hypot((b[0] - a[0]) * 101000, (b[1] - a[1]) * 111000)
        const steps = Math.max(1, Math.round(metres / 40))
        for (let k = 0; k < steps; k++) {
          const t = k / steps
          features.push({
            type: 'Feature',
            properties: { congestion: f.properties.congestion ?? 0 },
            geometry: {
              type: 'Point',
              coordinates: [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t],
            },
          })
        }
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
    active ? 'network-map-hover-status network-map-hover-status-active' : 'network-map-hover-status',
    active ? 'Click to open the simulation' : 'Simulation not available yet',
  )
  return box
}

function NetworkMap({
  bounds,
  segments,
  view = 'segments',
  intersections = [],
  selectedId,
  onSelect,
  onArrive,
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

  // create the map once
  useEffect(() => {
    const map = new MapLibreMap({
      container: containerRef.current,
      style: STYLE_URL,
      bounds,
      // leave room at the bottom for the timeline card that sits over the map
      fitBoundsOptions: { padding: { top: 20, right: 20, left: 20, bottom: 200 } },
      minZoom: 10,
      maxBounds: [
        [bounds[0][0] - 0.12, bounds[0][1] - 0.1],
        [bounds[1][0] + 0.12, bounds[1][1] + 0.1],
      ],
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
      map.addSource('heat', { type: 'geojson', data: EMPTY })
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
          type: 'heatmap',
          source: 'heat',
          layout: { visibility: 'none' },
          paint: {
            'heatmap-weight': ['get', 'congestion'],
            'heatmap-radius': ['interpolate', ['linear'], ['zoom'], 11, 10, 15, 30],
            'heatmap-intensity': ['interpolate', ['linear'], ['zoom'], 11, 0.6, 15, 1.4],
            'heatmap-color': [
              'interpolate',
              ['linear'],
              ['heatmap-density'],
              0,
              'rgba(0,0,0,0)',
              0.2,
              low,
              0.5,
              moderate,
              0.85,
              high,
            ],
            'heatmap-opacity': 0.75,
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
      map.on('click', 'intersections', (event) => {
        const props = event.features?.[0]?.properties
        if (!props?.active) return
        hoverCard.remove()
        zooming = true
        map.once('moveend', () => {
          zooming = false
        })
        onSelectRef.current?.(props.id)
      })
      map.on('mousemove', 'intersections', (event) => {
        const feature = event.features?.[0]
        if (!feature || zooming) return
        const { name, area, active } = feature.properties
        if (active) map.getCanvas().style.cursor = 'pointer'
        hoverCard
          .setLngLat(feature.geometry.coordinates)
          .setDOMContent(hoverContent(name, area, active))
          .addTo(map)
      })
      map.on('mouseleave', 'intersections', () => {
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
  }, [bounds])

  // segment data
  useEffect(() => {
    if (!ready) return
    const map = mapRef.current
    map.getSource('segments').setData(segments ?? EMPTY)
    map.getSource('heat').setData(heatPoints(segments))
  }, [ready, segments])

  // segments or heatmap
  useEffect(() => {
    if (!ready) return
    const map = mapRef.current
    map.setLayoutProperty('segments', 'visibility', view === 'segments' ? 'visible' : 'none')
    map.setLayoutProperty('heat', 'visibility', view === 'heatmap' ? 'visible' : 'none')
  }, [ready, view])

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
