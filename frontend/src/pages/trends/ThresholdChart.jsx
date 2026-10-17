import Card from '../../components/Card'
import EmptyState from '../../components/EmptyState'
import './ThresholdChart.css'

// Threshold exceedance by time window: for each window, on how many days of
// the period its rule was exceeded. The dashed line is the recurrence
// threshold: a window that reaches it counts as a recurring problem.
//
//   thresholds   data.thresholds: { totalDays, recurrenceDays, windows }
function ThresholdChart({ thresholds }) {
  const { totalDays, recurrenceDays, windows } = thresholds
  const markerAt = totalDays > 0 ? (recurrenceDays / totalDays) * 100 : 0

  const note = (
    <span className="th-note">
      <span className="th-note-line" aria-hidden="true" /> Recurrence threshold ({recurrenceDays} of{' '}
      {totalDays} days)
    </span>
  )

  if (windows.length === 0) {
    return (
      <Card title="Threshold exceedance by time window" action={note}>
        <EmptyState>No threshold rules apply to this selection.</EmptyState>
      </Card>
    )
  }

  return (
    <Card title="Threshold exceedance by time window" action={note}>
      <ul className="th-rows">
        {windows.map((w) => {
          const recurring = w.daysExceeded >= recurrenceDays
          const share = totalDays > 0 ? (w.daysExceeded / totalDays) * 100 : 0

          return (
            <li key={w.id} className="th-row">
              <div className="th-text">
                <span className="th-window">
                  {w.start}–{w.end}
                </span>
                <span className="th-rule">
                  {w.rule}
                  {w.location !== 'Intersection' && ` · ${w.location}`}
                </span>
              </div>

              <div
                className="th-track"
                role="img"
                aria-label={`${w.start}–${w.end}: exceeded on ${w.daysExceeded} of ${totalDays} days${recurring ? ', recurring' : ''}`}
                style={{ '--marker': `${markerAt}%` }}
              >
                <span
                  className={`th-fill ${recurring ? 'th-fill-recurring' : ''}`}
                  style={{ width: `${share}%` }}
                />
              </div>

              <div className="th-count">
                <span>
                  {w.daysExceeded} of {totalDays} days
                </span>
                {/* Said in words too, not only by the bar's color */}
                {recurring && <span className="th-flag">Recurring</span>}
              </div>
            </li>
          )
        })}
      </ul>
    </Card>
  )
}

export default ThresholdChart