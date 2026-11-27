import InfoTip from './InfoTip'
import KpiGroup from './KpiGroup'
import KpiTile from './KpiTile'
import LosBadge, { GRADES } from './LosBadge'
import { formatKpiValue, hasValue, KPI_DEFINITIONS, kpiTileProps } from '../utils/kpi'
import { losOf, summaryResults, summaryTiles } from '../utils/kpiNotes'
import './KpiSummary.css'

// The intersection's KPIs, for Current Traffic and Traffic Forecast: the level of service as a
// headline with what it means, then one KpiTile per KPI, two per row. As on every page,
// KpiGroup says once what the changes are compared with and how they were measured.
//
//   kpis        [{ current: KpiResult, previous: KpiResult }]
//   compared    what the change is measured against, e.g. "the 15 minutes before"
//   showNotes   false when the page shows summaryNotes() (utils/kpiNotes.js) itself, e.g. in
//               its card header

// What each level of service means
const LOS_WORDS = {
  A: 'Free flow',
  B: 'Light traffic',
  C: 'Moderate traffic',
  D: 'Heavy traffic',
  E: 'Very heavy traffic',
  F: 'Jammed',
}

function KpiSummary({ kpis, compared, showNotes = true }) {
  const los = losOf(kpis)
  const tiles = summaryTiles(kpis)
  const known = hasValue(los) && GRADES.includes(los.los_grade)

  return (
    <KpiGroup compared={compared} results={summaryResults(kpis)} showNotes={showNotes}>
      {los && (
        <div className="kpi-summary-los">
          <LosBadge grade={known ? los.los_grade : undefined} className="kpi-summary-los-badge" />
          <div className="kpi-summary-los-text">
            <p className="kpi-label">{KPI_DEFINITIONS.level_of_service.label}</p>
            <p className="kpi-summary-los-words">
              {known ? LOS_WORDS[los.los_grade] : formatKpiValue(los)}
              {!known && los.reason && (
                <InfoTip label="Why there is no value">{los.reason}</InfoTip>
              )}
            </p>
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
