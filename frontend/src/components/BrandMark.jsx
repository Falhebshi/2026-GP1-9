import './BrandMark.css'

// The small Jaadah logo square, shown before the name "Jaadah".
// Used in the nav bar, the Welcome page footer and the Login page.
//
//   size   "sm" (20px, footers)  or  "md" (28px, the nav bar and the
//          Login page). Default "sm".
//
// It is decoration only: put the word "Jaadah" next to it as real text.
function BrandMark({ size = 'sm', className = '' }) {
  return (
    <span
      className={`brand-mark brand-mark-${size} ${className}`}
      aria-hidden="true"
    />
  )
}

export default BrandMark
