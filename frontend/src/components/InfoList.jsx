import './InfoList.css'

// Rows of "label on the left, value on the right".
//
//   items   the rows, as a list: [{ label: 'Approaches', value: '4 approaches' }]
//
// A value can be text, a number, or another component such as a Badge.
// A row whose value is missing shows "Unavailable" instead of a blank.
function InfoList({ items, className = '' }) {
  return (
    <dl className={`info-list ${className}`}>
      {items.map((item) => (
        <div key={item.label} className="info-row">
          <dt className="info-label">{item.label}</dt>
          <dd className="info-value">
            {item.value ?? <span className="info-unavailable">Unavailable</span>}
          </dd>
        </div>
      ))}
    </dl>
  )
}

export default InfoList