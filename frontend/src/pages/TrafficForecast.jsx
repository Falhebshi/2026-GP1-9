import { useEffect, useState } from 'react'
import AlertList from '../components/AlertList'
import { ApproachDetails } from '../components/ApproachPanel'
import Badge from '../components/Badge'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import ForecastSimulation from '../components/ForecastSimulation'
import KpiSummary from '../components/KpiSummary'
import Notice from '../components/Notice'
import useFullScreen from '../hooks/useFullScreen'
import usePlayback from '../hooks/usePlayback'
import { getForecast } from '../services/forecastService'
import './TrafficForecast.css'

// Traffic Forecast page, laid out like Current Traffic: the predicted KPIs, the forecast alerts
// and the selected approach on the left, the predicted traffic in 3D with the 15 / 30 / 45 /
// 60 min play bar on the right. The KPIs and the approach show the horizon being played. The
// scene can be shown full screen; the selected approach then sits next to it.
function TrafficForecast() {
  const [data, setData] = useState(null) // the forecast, once it arrives
  const [error, setError] = useState(null) // the error message, if loading failed
  const [loadError, setLoadError] = useState(null) // the scene's data could not be loaded
  const [openApproachId, setOpenApproachId] = useState(null)
  const [startTime] = useState(() => new Date()) // the forecast starts from now
  const playback = usePlayback({ duration: 3600 })
  const { ref: sceneRef, fullScreen, toggle: toggleFullScreen } = useFullScreen()

  // Load the forecast once, when the page opens
  useEffect(() => {
    let cancelled = false // true if the user leaves before the data arrives

    getForecast()
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message)
      })

    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return (
      <EmptyState variant="error" title="Forecast unavailable">
        {error}
      </EmptyState>
    )
  }

  if (!data) {
    return <EmptyState>Loading forecast…</EmptyState>
  }

  // the horizon is the next mark ahead of the playhead, so the KPIs show the stretch being played
  const horizon = Math.min(3600, Math.max(900, Math.ceil(playback.time / 900) * 900))
  const minutes = horizon / 60
  const kpis = data.kpis[minutes] ?? []
  const approaches = data.approaches?.[minutes] ?? []
  const openApproach = approaches.find((a) => a.approach_id === openApproachId)
  const shown = new Date(startTime.getTime() + playback.time * 1000)

  const details = openApproach && (
    <ApproachDetails approach={openApproach} onClose={() => setOpenApproachId(null)} />
  )

  // the predicted time, its badge and the full screen button: above both columns, or inside the
  // scene in full screen
  const timeBar = (
    <div className="traffic-forecast-time">
      <span className="traffic-forecast-time-value">{formatLabel(shown)}</span>
      <span className="traffic-forecast-ahead">+{Math.floor(playback.time / 60)} min</span>
      <Badge variant="count">Forecast</Badge>
      <Button size="sm" variant="secondary" onClick={toggleFullScreen}>
        {fullScreen ? 'Exit full screen' : 'Full screen'}
      </Button>
    </div>
  )

  return (
    <div className="traffic-forecast">
      {data.isSample && (
        <Notice variant="warning">
          Sample data for layout only: the predicted KPIs and alerts on this page are illustrative,
          not forecast results, and the vehicles come from a test run.
        </Notice>
      )}
      {!fullScreen && timeBar}

      <div className="traffic-forecast-layout">
        <aside className="traffic-forecast-side">
          {!fullScreen && details}

          <Card title={`Predicted KPIs · in ${minutes} min`}>
            {kpis.length ? (
              <KpiSummary kpis={kpis} compared="now" />
            ) : (
              <EmptyState>No predicted KPIs are available for this horizon.</EmptyState>
            )}
          </Card>

          <AlertList
            title="Forecast Alerts"
            alerts={data.alerts}
            emptyMessage="No traffic problems are forecast."
          />
        </aside>

        <div ref={sceneRef} className="traffic-forecast-scene">
          {fullScreen && timeBar}

          <div className="traffic-forecast-stage">
            {fullScreen && details && (
              <div className="traffic-forecast-fullscreen-side">{details}</div>
            )}
            <ForecastSimulation
              intersection={data.intersection}
              playback={playback}
              shown={shown}
              horizon={horizon}
              approaches={approaches}
              openApproachId={openApproachId}
              onApproachChange={setOpenApproachId}
              height={fullScreen ? '100%' : 520}
              error={loadError}
              onLoadError={setLoadError}
            />
          </div>
        </div>
      </div>
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

export default TrafficForecast
