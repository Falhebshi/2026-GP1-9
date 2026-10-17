import './SceneNavControls.css'

// North arrow and camera buttons for TrafficScene3D.
//   NorthArrow         bearing: current camera bearing, in degrees (the arrow turns with it)
//   SceneNavControls   see the comment above the function

export function NorthArrow({ bearing = 0 }) {
  return (
    <div className="scene-nav-north" title="North" style={{ '--bearing': `${-bearing}deg` }}>
      <svg width="34" height="34" viewBox="-17 -17 34 34">
        <circle className="scene-nav-north-dial" r="16" />
        <path className="scene-nav-north-tip" d="M0 -12 L5 3 L0 0 L-5 3 Z" />
        <path
          className="scene-nav-north-tail"
          d="M0 12 L5 3 L0 0 L-5 3 Z"
          transform="rotate(180)"
        />
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
    <div className="scene-nav">
      <button
        title="Reset to north-up"
        className="scene-nav-compass"
        onClick={() => onNudge(() => ({ bearing: 0 }))}
      >
        <NorthArrow bearing={bearing} />
      </button>
      <div className="scene-nav-group">
        <button title="Zoom in" onClick={() => onNudge((v) => ({ zoom: v.zoom + 0.6 }))}>
          +
        </button>
        <button title="Zoom out" onClick={() => onNudge((v) => ({ zoom: v.zoom - 0.6 }))}>
          −
        </button>
      </div>
      <div className="scene-nav-group">
        <button title="Rotate left" onClick={() => onNudge((v) => ({ bearing: v.bearing - 45 }))}>
          ⟲
        </button>
        <button title="Rotate right" onClick={() => onNudge((v) => ({ bearing: v.bearing + 45 }))}>
          ⟳
        </button>
      </div>
      <div className="scene-nav-group">
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
