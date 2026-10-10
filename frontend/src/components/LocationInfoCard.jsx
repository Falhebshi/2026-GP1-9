import Card from './Card'
import InfoList from './InfoList'

// The "Location & General Information" card shown on Current Traffic,
// Traffic Forecast and Traffic Patterns & Trends.
//
//   intersection   the selected intersection, as an object:
//                  { name, area, approaches, signalType }
//   floating       adds a shadow, for when the card sits on top of the map
//
// Any field that is missing shows "Unavailable". The same happens for every
// row if the intersection itself has not loaded yet.
//
// This is the ONE place that turns intersection data into rows. If the
// backend names a field differently, change it here and all pages follow.
function LocationInfoCard({ intersection, floating = false, className = '' }) {
  const approaches = intersection?.approaches

  const items = [
    { label: 'Name', value: intersection?.name },
    { label: 'Area', value: intersection?.area },
    {
      label: 'Approaches',
      value: typeof approaches === 'number' ? `${approaches} approaches` : undefined,
    },
    { label: 'Signal type', value: intersection?.signalType },
  ]

  return (
    <Card
      title="Location & General Information"
      floating={floating}
      className={className}
    >
      <InfoList items={items} />
    </Card>
  )
}

export default LocationInfoCard