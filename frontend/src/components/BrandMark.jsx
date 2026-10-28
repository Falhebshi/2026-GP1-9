import './BrandMark.css'

// The small Jaadah logo square, shown before the name "Jaadah"
// (on the Login page, for example).
//
//   size   "sm" (20px)  or  "md" (28px). Default "sm".
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
