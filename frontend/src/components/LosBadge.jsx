import './LosBadge.css'

// A level-of-service grade, A to F, as a small colored square.
// The colors run from light (A, free flow) to dark (F, breakdown).
//
//   grade   'A' to 'F'. Leave it out when there is no grade: the badge
//           then shows a dash instead of a misleading letter.
//   label   text read out by screen readers (optional)
function LosBadge({ grade, label, className = '' }) {
  const known = GRADES.includes(grade)

  return (
    <span
      className={`los-badge ${known ? `los-badge-${grade.toLowerCase()}` : 'los-badge-none'} ${className}`}
      title={known ? `Level of service ${grade}` : 'Level of service unavailable'}
      aria-label={label ?? (known ? `Level of service ${grade}` : 'Level of service unavailable')}
    >
      {known ? grade : '–'}
    </span>
  )
}

export const GRADES = ['A', 'B', 'C', 'D', 'E', 'F']

export default LosBadge