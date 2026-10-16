import { useState } from 'react'
import AlertList from '../components/AlertList'
import Card from '../components/Card'
import ForecastSimulation from '../components/ForecastSimulation'
import KpiTile from '../components/KpiTile'
import { SAMPLE_FORECAST_ALERTS, SAMPLE_FORECAST_KPIS } from '../services/forecastData'
import './TrafficForecast.css'

// Traffic Forecast page: the predicted traffic in 3D with the 15 / 30 / 45 / 60 min play bar,
// then the predicted KPIs for the chosen horizon and the forecast alerts.
function TrafficForecast() {
  const [horizon, setHorizon] = useState(15) // minutes ahead

  return (
    <div className="traffic-forecast">
      <ForecastSimulation onHorizonChange={setHorizon} />

      <div className="traffic-forecast-row">
        <Card title={`Predicted KPIs · in ${horizon} min`}>
          <div className="traffic-forecast-kpis">
            {SAMPLE_FORECAST_KPIS[horizon].map((kpi) => (
              <KpiTile key={kpi.label} {...kpi} />
            ))}
          </div>
        </Card>

        <AlertList
          title="Forecast Alerts"
          alerts={SAMPLE_FORECAST_ALERTS}
          emptyMessage="No traffic problems are forecast."
        />
      </div>
    </div>
  )
}

export default TrafficForecast
