import { useEffect, useRef, useState } from 'react'
import { ClipExtension } from '@deck.gl/extensions'
import { SolidPolygonLayer } from '@deck.gl/layers'
import {
  Deck,
  MapView,
  WebMercatorViewport,
  FlyToInterpolator,
  LightingEffect,
  AmbientLight,
  DirectionalLight,
} from '@deck.gl/core'
import { prepareNetwork, roadLayers } from '../simulation_3d/roadLayers'
import { prepareSignals, signalLayers } from '../simulation_3d/signals'
import { prepareBuildings, buildingLayers } from '../simulation_3d/buildings'
import { prepareContext } from '../simulation_3d/context'
import { prepareLaneIndex, approachLanes } from '../simulation_3d/laneIndex'
import { prepareVegetation, vegetationLayers } from '../simulation_3d/vegetation'
import { vehicleIntervals, vehicleStates, vehicleLayers } from '../simulation_3d/vehicles'
import { ENV, envLighting } from '../simulation_3d/palette'
import { getIntersectionScene, getVehicleInterval } from '../services/simulationService'
import SceneNavControls from './SceneNavControls'
import ApproachPanel from './ApproachPanel'
import SegmentedControl from './SegmentedControl'
import './TrafficScene3D.css'

// 3D view of one intersection: roads, markings, the underpass, buildings and signals that change
// with the simulation time, and the approaches along the bottom. Clicking an approach (its chip or
// its lanes on the map) highlights its lanes and opens its KPIs and movements.
// Goes inside <SimulationViewport> and keeps the top-left corner free for the viewport's card.
//
//   intersectionId   folder in public/data, e.g. "INT_001"
//   center           [longitude, latitude] the camera starts over
//   scenario         "baseline" (default) or an intervention run
//   time             seconds from the start of the analysis period (optional, without it the scene
//                    loops through the analysis period by itself)
//   bounds           study area { west, south, east, north }, everything outside is cut off
//   night            how dark it is, from 0 (day) to 1 (night); in between for dusk
//   belowStatus      true when the viewport shows its time label in the top right corner, so the
//                    scene's own buttons move down below it
//   approaches       approaches with their KPIs for the panel (see services/currentTrafficService.js)
//   onReady          called with { duration } once the data is loaded
//   onError          called with a message if loading fails
// Cars and signal indications come from the SUMO run (run.json, its 15-minute vehicle files and
// signals.json); cars inside the tunnel are not shown. Only the analysis period is shown, never the
// warm-up (the network filling up) or the clearance (the last cars finishing).

const VIEWS = {
  '3d': { pitch: 50, bearing: -25 },
  top: { pitch: 0, bearing: 0 },
}
// how much ground the first view shows across the smaller side of the box, in metres. The signal
// heads cover about 65 x 50 m, so this keeps the whole intersection and all its signals in view.
const START_VIEW_M = { '3d': 150, top: 190 }
const clamp = (v, [a, b]) => Math.min(b, Math.max(a, v))
// Fade road paint out between zoom 16.8 and 16.2 so it doesn't turn into stripes
const paintOpacityFor = (zoom) => Math.min(1, Math.max(0, (zoom - 16.2) / 0.6))
// Same for the tunnel roof slats, between zoom 18.0 and 17.2
const slatOpacityFor = (zoom) => Math.min(1, Math.max(0, (zoom - 17.2) / 0.8))

// Sun color through the evening: white daylight, warm orange around sunset, cool blue moonlight
const SUN_COLORS = [
  [0, [255, 250, 240]],
  [0.35, [255, 196, 140]],
  [1, [170, 190, 255]],
]
function sunColor(n) {
  const i = n <= SUN_COLORS[1][0] ? 0 : 1
  const [a, ca] = SUN_COLORS[i]
  const [b, cb] = SUN_COLORS[i + 1]
  const k = Math.min(1, Math.max(0, (n - a) / (b - a)))
  return ca.map((v, j) => Math.round(v + (cb[j] - v) * k))
}

// Lighting for n between 0 (day) and 1 (night), without shadows
function makeLighting(n) {
  const L = envLighting(n)
  return new LightingEffect({
    ambient: new AmbientLight({ color: L.ambientColor, intensity: L.ambient }),
    sun: new DirectionalLight({
      color: sunColor(n),
      intensity: L.sun,
      direction: [1, 1.2, -2.2],
      _shadow: false,
    }),
  })
}

const VIEW_OPTIONS = [
  { value: '3d', label: '3D' },
  { value: 'top', label: 'Top' },
]
const TOOLTIP_STYLE = {
  background: 'var(--color-text)',
  color: 'var(--color-text-on-dark)',
  fontSize: 'var(--text-xs)',
  padding: 'var(--space-xs) var(--space-sm)',
  borderRadius: 'var(--radius)',
}

const CLIP = new ClipExtension()

function TrafficScene3D({
  intersectionId,
  center,
  bounds,
  night = 0,
  approaches,
  belowStatus = false,
  scenario = 'baseline',
  time,
  onReady,
  onError,
}) {
  // Clip every layer to the study area and keep the camera inside it
  const clipBounds = [bounds.west, bounds.south, bounds.east, bounds.north]
  const clip = (layers) =>
    layers.map((l) => l.clone({ extensions: [...(l.props.extensions || []), CLIP], clipBounds }))
  const hostRef = useRef(null)

  // zoom where START_VIEW_M metres fit across the smaller side of the box
  function startZoom(mode) {
    const w = hostRef.current?.clientWidth || 800
    const h = hostRef.current?.clientHeight || 600
    const metresPerPixelAtZoom0 = (40075016.686 * Math.cos((center[1] * Math.PI) / 180)) / 512
    return Math.log2((metresPerPixelAtZoom0 * Math.min(w, h)) / START_VIEW_M[mode])
  }

  // Keep the camera inside the square: you can't zoom out or move past its edges. If a move would
  // go too far, the view zooms back in or slides back.
  function fitView(v) {
    const width = hostRef.current?.clientWidth || 800
    const height = hostRef.current?.clientHeight || 600
    const mPerDegLon = 111320 * Math.cos((center[1] * Math.PI) / 180)
    const mPerDegLat = 110540
    const widthM = (bounds.east - bounds.west) * mPerDegLon
    const heightM = (bounds.north - bounds.south) * mPerDegLat

    // where the lower half of the box hits the ground, in metres from the camera centre. When the
    // camera is tilted the upper half looks far into the distance, so that part is allowed to see
    // past the edge (it shows the plain ground around the square)
    const viewport = new WebMercatorViewport({ ...v, width, height })
    let corners = [
      [0, (v.pitch || 0) < 12 ? 0 : height / 2],
      [width, (v.pitch || 0) < 12 ? 0 : height / 2],
      [0, height],
      [width, height],
    ].map((point) => {
      const [lon, lat] = viewport.unproject(point)
      return [(lon - v.longitude) * mPerDegLon, (lat - v.latitude) * mPerDegLat]
    })

    // seeing more ground than the square holds: zoom in until it fits
    let zoom = v.zoom
    const spanX = Math.max(...corners.map((c) => c[0])) - Math.min(...corners.map((c) => c[0]))
    const spanY = Math.max(...corners.map((c) => c[1])) - Math.min(...corners.map((c) => c[1]))
    const tooBig = Math.max(spanX / widthM, spanY / heightM)
    if (tooBig > 1) {
      zoom += Math.log2(tooBig)
      corners = corners.map(([x, y]) => [x / tooBig, y / tooBig])
    }

    // then slide the centre so no corner is outside
    const minX = Math.min(...corners.map((c) => c[0]))
    const maxX = Math.max(...corners.map((c) => c[0]))
    const minY = Math.min(...corners.map((c) => c[1]))
    const maxY = Math.max(...corners.map((c) => c[1]))
    const keepInside = (value, low, high) =>
      low > high ? (low + high) / 2 : clamp(value, [low, high])
    return {
      ...v,
      zoom,
      longitude: keepInside(
        v.longitude,
        bounds.west - minX / mPerDegLon,
        bounds.east - maxX / mPerDegLon,
      ),
      latitude: keepInside(
        v.latitude,
        bounds.south - minY / mPerDegLat,
        bounds.north - maxY / mPerDegLat,
      ),
    }
  }

  // Plain ground around the square, so tilting the camera shows land instead of an empty sky
  function outerGround() {
    const pad = 0.05
    const sand = [190, 183, 168]
    const dark = [6, 10, 24]
    const mix = (k) => sand.map((v, i) => Math.round(v + (dark[i] - v) * 0.8 * k))
    return new SolidPolygonLayer({
      id: 'outer-ground',
      data: [0],
      getPolygon: () => [
        [bounds.west - pad, bounds.south - pad],
        [bounds.east + pad, bounds.south - pad],
        [bounds.east + pad, bounds.north + pad],
        [bounds.west - pad, bounds.north + pad],
      ],
      getFillColor: mix(ENV.n),
      material: false,
      parameters: { depthCompare: 'always', depthWriteEnabled: false },
      updateTriggers: { getFillColor: ENV.n },
    })
  }
  const deckRef = useRef(null)
  const sceneRef = useRef(null) // prepared data: { net, sig, bld, ctx, ss, veg, laneIndex }
  const staticLayersRef = useRef([])
  const lastSigRef = useRef(null)
  const tRef = useRef(time ?? 0)
  const startRef = useRef(0) // scene time of the start of the analysis period
  const autoplay = time === undefined
  const hoverRef = useRef(null)
  const selRef = useRef(null)
  const paintRef = useRef(paintOpacityFor(18))
  const slatRef = useRef(slatOpacityFor(18))
  const xrayRef = useRef(false)
  const showCtxRef = useRef(true)
  const topRef = useRef(true) // starts in Top view
  const vsRef = useRef(null)
  const vsTimerRef = useRef(0)
  const draggingRef = useRef(false)
  const envAnimRef = useRef(0)
  const callbacksRef = useRef({ onReady, onError })
  callbacksRef.current = { onReady, onError }

  const base = (mode) => ({
    longitude: center[0],
    latitude: center[1],
    ...VIEWS[mode],
    zoom: startZoom(mode),
    minZoom: 16,
    maxZoom: 21,
    maxPitch: 58,
  })

  const [status, setStatus] = useState('loading') // loading | ready | error
  const [mode, setMode] = useState('top')
  const [viewState, setViewState] = useState(() => base('top'))
  const [openApproach, setOpenApproach] = useState(null)

  // Roads, markings and buildings only need rebuilding when hover, selection or view changes
  function rebuildStatic() {
    const s = sceneRef.current
    if (!s) return
    staticLayersRef.current = [
      outerGround(),
      ...clip([
        ...roadLayers(s.net, {
          selectedIds: selRef.current,
          xray: xrayRef.current,
          paintOpacity: paintRef.current,
          slatOpacity: slatRef.current,
          night: ENV.n,
          context: s.ctx,
          showContext: showCtxRef.current,
          streetscape: s.ss,
          show3d: true,
        }),
        ...buildingLayers(s.bld, { top: topRef.current, night: ENV.n }),
        ...vegetationLayers(s.veg),
      ]),
    ]
    redraw()
  }
  // signalLayers() returns the same layers until a light changes color, so we skip the update otherwise
  function redraw(force = true) {
    const s = sceneRef.current
    if (!deckRef.current || !s) return
    const t = tRef.current
    const dyn = signalLayers(s.sig, t, { top: topRef.current })
    // cars move every frame, so with cars the scene is always redrawn
    if (!force && !s.veh && dyn === lastSigRef.current) return
    lastSigRef.current = dyn
    const vehicles = s.veh?.at(t) // null while this interval's file is still loading
    const cars = vehicles ? vehicleLayers(vehicleStates(vehicles, t), t) : []
    deckRef.current.setProps({ layers: [...staticLayersRef.current, ...clip(cars), ...clip(dyn)] })
  }

  // Set up deck.gl and load the data. The canvas is made here and removed on clean-up so it works
  // with StrictMode mounting twice in development.
  useEffect(() => {
    const canvas = document.createElement('canvas')
    canvas.className = 'traffic-scene-canvas'
    hostRef.current.prepend(canvas)
    vsRef.current = fitView(base('top')) // opens in Top view

    const deck = new Deck({
      canvas,
      // Push the far plane back so the tunnel ramps (about 7 m below street level) don't get clipped
      views: new MapView({ repeat: false, farZMultiplier: 3 }),
      width: '100%',
      height: '100%',
      initialViewState: vsRef.current,
      controller: {
        dragRotate: true,
        touchRotate: true,
        inertia: 350,
        scrollZoom: { smooth: true, speed: 0.02 },
      },
      useDevicePixels: true,
      pickingRadius: 6, // lanes are thin on screen, so give a few pixels of slack
      getCursor: ({ isDragging }) =>
        isDragging ? 'grabbing' : hoverRef.current ? 'pointer' : 'grab',
      effects: [makeLighting(ENV.n)],
      onInteractionStateChange: (st) => {
        draggingRef.current = !!(st.isDragging || st.isPanning || st.isRotating)
      },
      onViewStateChange: ({ viewState: v }) => {
        const vs = fitView(v)
        vsRef.current = vs
        if (!vsTimerRef.current)
          vsTimerRef.current = setTimeout(() => {
            vsTimerRef.current = 0
            setViewState(vsRef.current)
          }, 100)
        const top = vs.pitch < 12
        if (top !== topRef.current) {
          topRef.current = top
          rebuildStatic()
        }
        const op = paintOpacityFor(vs.zoom),
          so = slatOpacityFor(vs.zoom)
        const changed = (a, b) => Math.abs(a - b) > 0.05 || (a !== b && (a === 0 || a === 1))
        if (changed(op, paintRef.current) || changed(so, slatRef.current)) {
          paintRef.current = op
          slatRef.current = so
          rebuildStatic()
        }
        return vs
      },
      // Only the lanes that lead into the junction react to the mouse, since those are the ones
      // that open an approach
      onHover: ({ object }) => {
        if (draggingRef.current) return
        const id = approachLane(object) ? object.properties.id : null
        if (id !== hoverRef.current) {
          hoverRef.current = id
          rebuildStatic()
        }
      },
      // Clicking a lane that leads into the junction opens its approach, clicking empty ground
      // closes it
      onClick: ({ object }) => {
        const lane = approachLane(object)
        if (lane) openArm(lane.arm)
        else if (!object) openArm(null)
      },
      getTooltip: ({ object }) => {
        const p = object?.properties
        if (!p) return null
        // only the approach lanes have a tooltip
        const html =
          p.kind === 'lane' &&
          approachLane(object) &&
          `<b>${approachLane(object).arm} approach</b><br/>Click to see its KPIs`
        return html && { html, style: TOOLTIP_STYLE }
      },
      layers: [],
    })
    deckRef.current = deck

    let cancelled = false,
      raf = 0,
      last = performance.now()
    getIntersectionScene(intersectionId, scenario)
      .then((d) => {
        if (cancelled) return
        const sig = prepareSignals(d.signalHeads, d.signals)
        // the analysis period of the run; no run yet: the lights stay red, the scene loops 2 minutes
        const from = d.run?.analysis_start_s ?? 0
        const to = d.run?.analysis_end_s ?? 120
        startRef.current = from
        tRef.current = from + (time ?? 0)
        sceneRef.current = {
          net: prepareNetwork({
            surface: d.surface,
            markings: d.markings,
            arrows: d.arrows,
            underpass: d.underpass,
            detail: d.detail,
          }),
          sig,
          bld: prepareBuildings(d.buildings, center),
          ctx: prepareContext(d.context),
          ss: d.streetscape.features,
          veh: d.run
            ? vehicleIntervals(d.run, (file) => getVehicleInterval(intersectionId, scenario, file))
            : null,
          veg: null,
          laneIndex: prepareLaneIndex({
            surface: d.surface,
            detail: d.detail,
            arrows: d.arrows,
            center,
          }),
        }
        sceneRef.current.approachLanes = approachLanes(sceneRef.current.laneIndex, sig)
        sceneRef.current.veg = prepareVegetation({
          streetscape: sceneRef.current.ss,
          context: sceneRef.current.ctx,
          signals: sig,
          center,
          roofs: d.underpass.features.filter((f) => f.properties.kind === 'roof'),
          planting: d.planting,
        })
        setStatus('ready')
        callbacksRef.current.onReady?.({ duration: to - from })
        rebuildStatic()
        // No time from the page, so loop the run at real speed
        if (autoplay) {
          const tick = (now) => {
            const dt = (now - last) / 1000
            last = now
            let nt = tRef.current + dt
            if (nt > to) nt = from
            tRef.current = nt
            redraw(false)
            raf = requestAnimationFrame(tick)
          }
          raf = requestAnimationFrame(tick)
        }
      })
      .catch(() => {
        if (cancelled) return
        setStatus('error')
        callbacksRef.current.onError?.(
          'The simulation data for this intersection could not be loaded.',
        )
      })

    return () => {
      cancelled = true
      cancelAnimationFrame(raf)
      cancelAnimationFrame(envAnimRef.current)
      clearTimeout(vsTimerRef.current)
      deck.finalize()
      canvas.remove()
      deckRef.current = null
      sceneRef.current = null
    }
    // Only rebuild for a new intersection or scenario
  }, [intersectionId, scenario]) // eslint-disable-line react-hooks/exhaustive-deps

  // Follow the time from the page, e.g. usePlayback
  useEffect(() => {
    if (time === undefined) return
    tRef.current = startRef.current + time
    redraw(false)
  }, [time]) // eslint-disable-line react-hooks/exhaustive-deps

  // The lane under the mouse if it is part of an approach, otherwise null
  function approachLane(object) {
    const p = object?.properties
    if (p?.kind !== 'lane') return null
    const groups = sceneRef.current?.approachLanes ?? {}
    const arm = Object.keys(groups).find((name) => groups[name].has(p.id))
    return arm ? { id: p.id, arm } : null
  }

  // Open an approach by its arm ('North', 'East'...) and highlight its lanes. Opening the open one again closes it.
  function openArm(arm) {
    const current = selRef.current?.arm
    const next = arm && arm !== current ? arm : null
    const lanes = sceneRef.current?.approachLanes?.[next]
    selRef.current = next && lanes ? Object.assign(new Set(lanes), { arm: next }) : null
    setOpenApproach(next)
    rebuildStatic()
  }

  // Blend lighting and colors to the new darkness over about 1.5 s
  useEffect(() => {
    const to = Math.min(1, Math.max(0, Number(night) || 0)),
      from = ENV.n,
      t0 = performance.now()
    if (from === to) {
      deckRef.current?.setProps({ effects: [makeLighting(ENV.n)] })
      rebuildStatic()
      return
    }
    cancelAnimationFrame(envAnimRef.current)
    const step = (now) => {
      const k = Math.min(1, (now - t0) / 1500),
        e = k * k * (3 - 2 * k)
      ENV.n = from + (to - from) * e
      ENV.ambient = envLighting(ENV.n).ambient
      deckRef.current?.setProps({ effects: [makeLighting(ENV.n)] })
      rebuildStatic()
      if (k < 1) envAnimRef.current = requestAnimationFrame(step)
    }
    envAnimRef.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(envAnimRef.current)
  }, [night]) // eslint-disable-line react-hooks/exhaustive-deps

  function switchView(m) {
    setMode(m)
    deckRef.current?.setProps({
      initialViewState: {
        ...fitView(base(m)),
        transitionDuration: 900,
        transitionInterpolator: new FlyToInterpolator(),
      },
    })
  }
  // Used by the camera buttons (zoom, rotate, tilt, reset north)
  function nudge(change) {
    const v = vsRef.current
    const next = { ...v, ...change(v) }
    next.zoom = clamp(next.zoom, [16, 21])
    next.pitch = clamp(next.pitch, [0, 58])
    vsRef.current = fitView({ ...base(mode), ...next })
    deckRef.current?.setProps({
      initialViewState: { ...vsRef.current, transitionDuration: 350 },
    })
  }

  return (
    <div
      ref={hostRef}
      className={`traffic-scene ${belowStatus ? 'traffic-scene-below-status' : ''}`}
      style={{ '--night': night }}
    >
      {/* the canvas gets added here by the effect above */}
      {status === 'loading' && <div className="traffic-scene-note">Loading simulation…</div>}

      <div className="traffic-scene-right">
        <SceneNavControls bearing={viewState.bearing} onNudge={nudge} />
      </div>

      <div className="traffic-scene-bottom-left">
        {status === 'ready' && (
          <ApproachPanel
            approaches={approaches}
            openId={approaches?.find((a) => a.arm === openApproach)?.approach_id ?? null}
            onToggle={(id) => openArm(approaches.find((a) => a.approach_id === id)?.arm ?? null)}
          />
        )}
      </div>

      <div className="traffic-scene-top-right">
        <SegmentedControl
          ariaLabel="Camera view"
          size="sm"
          options={VIEW_OPTIONS}
          value={mode}
          onChange={switchView}
        />
      </div>
    </div>
  )
}

export default TrafficScene3D
