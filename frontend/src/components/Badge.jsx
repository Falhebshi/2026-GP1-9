import './Badge.css'

// A small pill for a count or a status.
//
//   variant   "count"    filled indigo, for numbers such as the alert count
//             "neutral"  soft lavender, for plain labels
//             "success"  green   (good / resolved)
//             "warning"  amber   (active / needs attention)
//             "danger"   red     (severe)
function Badge({ variant = 'neutral', children }) {
  return <span className={`badge badge-${variant}`}>{children}</span>
}

export default Badge