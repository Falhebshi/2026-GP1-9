import { useEffect, useState } from 'react'
import Badge from './Badge'
import LocationSummary from './LocationSummary'
import PlaybackBar from './PlaybackBar'
import SimulationViewport from './SimulationViewport'
import TrafficScene3D from './TrafficScene3D'
import usePlayback from '../hooks/usePlayback'
import { darkness } from '../utils/daylight'
import './ForecastSimulation.css'

// The 3D simulation for the Traffic Forecast page: the predicted next 60 minutes, played in
// accelerated time, with the team's PlaybackBar under it (marks at 15, 30, 45 and 60 min) and the
// predicted time above it. Clicking a mark jumps there. The horizon is the next mark ahead of the
// playhead, so the KPIs below show the prediction for the stretch being played.
//
//   intersection     the intersection to show: { id, center, bounds, name, area, ... }
//   start            the time the forecast starts from (a Date, now unless you say otherwise)
//   scenario         which simulation run to show ('forecast' when the backend provides it)
//   onHorizonChange  called with the horizon in minutes (15, 30, 45 or 60) when it changes
//   error            text to show instead of the simulation, e.g. when the forecast is unavailable

const HORIZONS = [
  { time: 900, label: '15' },
  { time: 1800, label: '30' },
  { time: 2700, label: '45' },
  { time: 3600, label: '60' },
]

function ForecastSimulation({ intersection, start, scenario = 'baseline', onHorizonChange, error }) {
  const [startTime] = useState(() => start ?? new Date())
  const [runLength, setRunLength] = useState(120)
  const [loadError, setLoadError] = useState(null)
  const playback = usePlayback({ duration: 3600 })
  const horizon = Math.min(3600, Math.max(900, Math.ceil(playback.time / 900) * 900))

  useEffect(() => {
    onHorizonChange?.(horizon / 60)
  }, [horizon, onHorizonChange])

  // The test run is shorter than the horizons, so it repeats. With the real forecast run the
  // length matches and this does nothing.
  const sceneTime = playback.time % runLength
  const shown = new Date(startTime.getTime() + playback.time * 1000)
  const minutes = Math.floor(playback.time / 60)

  return (
    <div className="forecast-sim">
      {/* the predicted time above the map, on the right, like on Current Traffic */}
      <div className="forecast-sim-time">
        <span className="forecast-sim-time-value">{formatLabel(shown)}</span>
        <span className="forecast-sim-ahead">+{minutes} min</span>
        <Badge variant="count">Forecast</Badge>
      </div>

      <SimulationViewport
        height={520}
        overlay={<LocationSummary intersection={intersection} />}
        error={error || loadError}
        footer={
          <PlaybackBar
            duration={3600}
            time={playback.time}
            onTimeChange={playback.setTime}
            playing={playback.playing}
            onPlayingChange={playback.setPlaying}
            speed={playback.speed}
            onSpeedChange={playback.setSpeed}
            marks={HORIZONS}
            selectedMark={horizon}
            onMarkSelect={playback.setTime}
            disabled={Boolean(error || loadError)}
          />
        }
      >
        <TrafficScene3D
          intersectionId={intersection.id}
          center={intersection.center}
          bounds={intersection.bounds}
          scenario={scenario}
          time={sceneTime}
          night={darkness(shown, intersection.center)}
          onReady={({ duration }) => setRunLength(duration || 120)}
          onError={setLoadError}
        />
      </SimulationViewport>
    </div>
  )
}

// e.g. "Thu 15 Oct, 16:45"
function formatLabel(date) {
  const day = date
    .toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })
    .replace(',', '')
  const time = date.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${day}, ${time}`
}

export default ForecastSimulation
