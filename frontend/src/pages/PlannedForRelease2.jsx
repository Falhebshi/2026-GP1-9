import EmptyState from '../components/EmptyState'
import './PlannedForRelease2.css'

// The page for a part of Jaadah that comes in Release 2 (Traffic Forecast, Alerts): its tab stays
// in the nav bar, and the page says it is planned instead of showing sample data.
//
//   title   the page's name, e.g. "Traffic Forecast"
function PlannedForRelease2({ title }) {
  return (
    <div className="planned">
      <h1 className="planned-title">{title}</h1>
      <EmptyState title="Release 2">This page is planned for Release 2.</EmptyState>
    </div>
  )
}

export default PlannedForRelease2
