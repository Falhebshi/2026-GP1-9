import LocationSummary from './LocationSummary'
import PlaybackBar from './PlaybackBar'
import SimulationViewport from './SimulationViewport'
import TrafficScene3D from './TrafficScene3D'
import { darkness } from '../utils/daylight'
import './ForecastSimulation.css'

// The 3D simulation for the Traffic Forecast page: the predicted next 60 minutes, played in
// accelerated time, with the team's PlaybackBar under it (marks at 15, 30, 45 and 60 min).
// Clicking a mark jumps there. The page owns the clock (usePlayback), so it can show the
// predicted time and the KPIs of the horizon being played.
//
//   intersection      the intersection to show: { id, center, bounds, name, area, ... }
//   playback          the clock from usePlayback({ duration: 3600 })
//   shown             the predicted time being played (a Date)
//   horizon           the next mark ahead of the playhead, in seconds (900 to 3600)
//   approaches        the predicted approaches of that horizon, for the chips on the scene
//   openApproachId    approach_id of the selected approach, or null
//   onApproachChange  called with an approach_id (or null) when one is selected or cleared
//   height            height of the scene in pixels, or '100%' in full screen
//   scenario          which simulation run to show ('forecast' when the backend provides it)
//   error             text to show instead of the simulation, e.g. when the forecast is unavailable
//   onLoadError       called with a message if the scene's data could not be loaded

const HORIZONS = [
  { time: 900, label: '15' },
  { time: 1800, label: '30' },
  { time: 2700, label: '45' },
  { time: 3600, label: '60' },
]

function ForecastSimulation({
  intersection,
  playback,
  shown,
  horizon,
  approaches,
  openApproachId,
  onApproachChange,
  height = 520,
  scenario = 'baseline',
  error,
  onLoadError,
}) {
  return (
    <SimulationViewport
      height={height}
      className="forecast-sim"
      overlay={<LocationSummary intersection={intersection} />}
      error={error}
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
          disabled={Boolean(error)}
        />
      }
    >
      <TrafficScene3D
        intersectionId={intersection.id}
        center={intersection.center}
        bounds={intersection.bounds}
        scenario={scenario}
        time={playback.time}
        night={darkness(shown, intersection.center)}
        approaches={approaches}
        openApproachId={openApproachId}
        onApproachChange={onApproachChange}
        onError={onLoadError}
      />
    </SimulationViewport>
  )
}

export default ForecastSimulation
