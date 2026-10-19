import { useState } from 'react'
import Card from '../../components/Card'
import EmptyState from '../../components/EmptyState'
import { GRADES } from '../../components/LosBadge'
import useElementWidth from '../../hooks/useElementWidth'
import './LosDistribution.css'

// A grade's letter is written inside its segment only when it fits
const MIN_LABEL_WIDTH = 20

// Level of service distribution: for the intersection and each approach,
// one bar split by the share of 15-minute intervals at each grade, A to F.
// The column on the right is the share at E or F (poor operation).
//
//   rows   data.losDistribution: [{ element: { id, label }, shares: { A … F } }]
function LosDistribution({ rows }) {
  const [hovered, setHovered] = useState(null) // { label, grade, share }
  const [ref, width] = useElementWidth() // width of one bar, for the letters

  if (rows.length === 0) {
    return (
      <Card title="Level of service distribution">
        <EmptyState>No performance data available for this period.</EmptyState>
      </Card>
    )
  }

  return (
    <Card title="Level of service distribution" className="losd-card">
      <div className="losd-head">
        <span>Share of 15-minute intervals</span>
        <span>At E or F</span>
      </div>

      <ul className="losd-rows" onPointerLeave={() => setHovered(null)}>
        {rows.map((row, index) => {
          const poor = (row.shares.E ?? 0) + (row.shares.F ?? 0)

          return (
            <li key={row.element.id} className="losd-row">
              <span className="losd-label">{row.element.label}</span>

              <div
                ref={index === 0 ? ref : undefined}
                className="losd-bar"
                role="img"
                aria-label={`${row.element.label}: ${GRADES.map((g) => `${g} ${percent(row.shares[g])}`).join(', ')}`}
              >
                {GRADES.map((grade) => {
                  const share = row.shares[grade] ?? 0
                  if (share <= 0) return null
                  const fits = share * width >= MIN_LABEL_WIDTH

                  return (
                    <span
                      key={grade}
                      className={`losd-seg losd-los-${grade.toLowerCase()}`}
                      style={{ flexGrow: share }}
                      onPointerEnter={() => setHovered({ label: row.element.label, grade, share })}
                    >
                      {fits ? grade : ''}
                    </span>
                  )
                })}
              </div>

              <span className="losd-poor">{percent(poor)}</span>
            </li>
          )
        })}
      </ul>

      {/* Legend: every grade, so small segments without a letter can still be read */}
      <div className="losd-legend">
        {GRADES.map((grade) => (
          <span key={grade} className="losd-legend-item">
            <span className={`losd-swatch losd-los-${grade.toLowerCase()}`} />
            {grade}
          </span>
        ))}
        <span className="losd-readout" aria-live="polite">
          {hovered
            ? `${hovered.label} · LOS ${hovered.grade} · ${percent(hovered.share)} of intervals`
            : ''}
        </span>
      </div>
    </Card>
  )
}

// 0.153 → "15%"
function percent(share) {
  return `${Math.round((share ?? 0) * 100)}%`
}

export default LosDistribution