import { Link } from 'react-router-dom'
import Card from './Card'
import InfoList from './InfoList'
import './AlertCard.css'

// One alert as a card: its title, a tag saying what kind of alert it is,
// its details, and a link to its Alert Details page. Used on the Alerts page.
//
//   type             "current", "forecast" or "pattern". Sets the tag.
//   title            e.g. "Queue spillback"
//   details          rows for an InfoList, e.g.
//                    [{ label: 'Affected area', value: 'North approach' }]
//   detailsTo        URL of its Alert Details page. Leave it out when the
//                    alert has no intervention: the card then says
//                    "No intervention available".
//
// The card stretches to the height of its row, so cards side by side in a
// grid line up even when one has more rows than the others.
function AlertCard({ type, title, details = [], detailsTo, className = '' }) {
  const tag = TYPES[type]

  return (
    <Card
      title={title}
      action={tag && <span className={`alert-card-tag alert-card-tag-${type}`}>{tag}</span>}
      className={`alert-card ${className}`}
    >
      <InfoList items={details} />

      <div className="alert-card-footer">
        {detailsTo ? (
          <Link to={detailsTo} className="alert-card-link">
            View details →
          </Link>
        ) : (
          <span className="alert-card-none">No intervention available</span>
        )}
      </div>
    </Card>
  )
}

// The text on each kind of tag
const TYPES = {
  current: 'Current',
  forecast: 'Forecast',
  pattern: 'Pattern',
}

export default AlertCard