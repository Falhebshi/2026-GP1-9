import { useEffect, useState } from 'react'
import AlertList from '../components/AlertList'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import ForecastSimulation from '../components/ForecastSimulation'
import KpiTile from '../components/KpiTile'
import { getForecast } from '../services/forecastService'
import './TrafficForecast.css'

// Traffic Forecast page: the predicted traffic in 3D with the 15 / 30 / 45 / 60 min play bar,
// then the predicted KPIs for the chosen horizon and the forecast alerts.
function TrafficForecast() {
  const [data, setData] = useState(null) // the forecast, once it arrives
  const [error, setError] = useState(null) // the error message, if loading failed
  const [horizon, setHorizon] = useState(15) // minutes ahead

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

  const kpis = data.kpis[horizon] ?? []

  return (
    <div className="traffic-forecast">
      <ForecastSimulation intersection={data.intersection} onHorizonChange={setHorizon} />

      <div className="traffic-forecast-row">
        <Card title={`Predicted KPIs · in ${horizon} min`}>
          {kpis.length ? (
            <div className="traffic-forecast-kpis">
              {kpis.map((kpi) => (
                <KpiTile key={kpi.label} {...kpi} />
              ))}
            </div>
          ) : (
            <EmptyState>No predicted KPIs are available for this horizon.</EmptyState>
          )}
        </Card>

        <AlertList
          title="Forecast Alerts"
          alerts={data.alerts}
          emptyMessage="No traffic problems are forecast."
        />
      </div>
    </div>
  )
}

export default TrafficForecast
