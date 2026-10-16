import './SceneNavControls.css'

// North arrow and camera buttons for TrafficScene3D.

export function NorthArrow({ bearing = 0 }) {
  return (
    <div className="north" title="North">
      <svg
        width="34"
        height="34"
        viewBox="-17 -17 34 34"
        style={{ transform: `rotate(${-bearing}deg)` }}
      >
        <circle r="16" fill="rgba(255,255,255,.92)" stroke="#c9ccd1" />
        <path d="M0 -12 L5 3 L0 0 L-5 3 Z" fill="#1f2937" />
        <path d="M0 12 L5 3 L0 0 L-5 3 Z" fill="#9ca3af" transform="rotate(180)" />
        <text y="-1" x="0" fontSize="0" />
      </svg>
      <span>N</span>
    </div>
  )
}

// Zoom, rotate 45°, tilt, and a compass that turns the map back to north.
//   bearing   current camera bearing, in degrees
//   onNudge   called with a function that returns the camera change
function SceneNavControls({ bearing = 0, onNudge }) {
  return (
    <div className="nav">
      <button
        title="Reset to north-up"
        className="nav-compass"
        onClick={() => onNudge(() => ({ bearing: 0 }))}
      >
        <NorthArrow bearing={bearing} />
      </button>
      <div className="nav-group">
        <button title="Zoom in" onClick={() => onNudge((v) => ({ zoom: v.zoom + 0.6 }))}>
          +
        </button>
        <button title="Zoom out" onClick={() => onNudge((v) => ({ zoom: v.zoom - 0.6 }))}>
          −
        </button>
      </div>
      <div className="nav-group">
        <button title="Rotate left" onClick={() => onNudge((v) => ({ bearing: v.bearing - 45 }))}>
          ⟲
        </button>
        <button title="Rotate right" onClick={() => onNudge((v) => ({ bearing: v.bearing + 45 }))}>
          ⟳
        </button>
      </div>
      <div className="nav-group">
        <button title="Tilt up (more 3D)" onClick={() => onNudge((v) => ({ pitch: v.pitch + 15 }))}>
          ⤒
        </button>
        <button
          title="Tilt down (flatter)"
          onClick={() => onNudge((v) => ({ pitch: v.pitch - 15 }))}
        >
          ⤓
        </button>
      </div>
    </div>
  )
}

export default SceneNavControls
