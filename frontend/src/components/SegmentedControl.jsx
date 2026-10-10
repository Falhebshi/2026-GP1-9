import './SegmentedControl.css'

// A row of buttons where exactly one is active, for switching between a few
// choices that should all stay visible (unlike a Select, which hides them).
//
//   options     the choices, as a list: [{ value: 'all', label: 'All days' }]
//   value       the value of the choice that is currently active
//   onChange    function called with the new value when the user clicks one
//   label       text shown before the buttons (optional)
//   ariaLabel   hidden description for screen readers; use it when there is
//               no visible label
//   size        "md" (normal)  or  "sm" (small, e.g. on top of the map)
function SegmentedControl({
  options,
  value,
  onChange,
  label,
  ariaLabel,
  size = 'md',
  className = '',
}) {
  return (
    <div className={`segmented-field ${className}`}>
      {label && <span className="segmented-label">{label}</span>}

      <div
        className={`segmented segmented-${size}`}
        role="group"
        aria-label={label || ariaLabel}
      >
        {options.map((option) => {
          const isActive = option.value === value

          return (
            <button
              key={option.value}
              type="button"
              className={`segmented-option ${isActive ? 'active' : ''}`}
              aria-pressed={isActive}
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export default SegmentedControl