import KpiGroup from './KpiGroup'
import KpiTile from './KpiTile'
import LosBadge, { GRADES } from './LosBadge'
import {
  formatKpiValue,
  hasValue,
  INTERSECTION_KPIS,
  KPI_DEFINITIONS,
  kpiTileProps,
} from '../utils/kpi'
import './KpiSummary.css'

// The intersection's KPIs, for Current Traffic and Traffic Forecast: the level of service as a
// headline with what it means and the A to F scale, then one KpiTile per KPI, two per row. As
// on every page, KpiGroup says once what the changes are compared with and how they were
// measured.
//
//   kpis       [{ current: KpiResult, previous: KpiResult }]
//   compared   what the change is measured against, e.g. "the 15 minutes before"

// The tiles: the intersection's KPIs (see INTERSECTION_KPIS) under the level of service
const TILES = INTERSECTION_KPIS.filter((kpi) => kpi !== 'level_of_service')

// What each level of service means
const LOS_WORDS = {
  A: 'Free flow',
  B: 'Light traffic',
  C: 'Moderate traffic',
  D: 'Heavy traffic',
  E: 'Very heavy traffic',
  F: 'Jammed',
}

function KpiSummary({ kpis, compared }) {
  const los = kpis.find((k) => k.current.kpi === 'level_of_service')?.current
  const tiles = TILES.map((kpi) => kpis.find((k) => k.current.kpi === kpi)).filter(Boolean)
  const known = hasValue(los) && GRADES.includes(los.los_grade)

  const results = [...(los ? [los] : []), ...tiles.map(({ current }) => current)]

  return (
    <KpiGroup compared={compared} results={results}>
      {los && (
        <div className="kpi-summary-los">
          <LosBadge grade={known ? los.los_grade : undefined} className="kpi-summary-los-badge" />
          <div className="kpi-summary-los-text">
            <p className="kpi-label">{KPI_DEFINITIONS.level_of_service.label}</p>
            <p className="kpi-summary-los-words">
              {known ? LOS_WORDS[los.los_grade] : formatKpiValue(los)}
            </p>
            {!known && los.reason && <p className="kpi-reason">{los.reason}</p>}
            {known && (
              <p className="kpi-summary-los-scale">
                {GRADES.map((grade) => (
                  <span
                    key={grade}
                    className={grade === los.los_grade ? 'kpi-summary-los-current' : undefined}
                  >
                    {grade}
                  </span>
                ))}
                <span className="kpi-summary-los-ends">A free flow · F jammed</span>
              </p>
            )}
          </div>
        </div>
      )}

      <div className="kpi-summary-tiles">
        {tiles.map(({ current, previous }) => (
          <KpiTile
            key={current.kpi}
            layout="stacked"
            label={KPI_DEFINITIONS[current.kpi].label}
            {...kpiTileProps(current, previous)}
            tag={undefined}
          />
        ))}
      </div>
    </KpiGroup>
  )
}

export default KpiSummary
