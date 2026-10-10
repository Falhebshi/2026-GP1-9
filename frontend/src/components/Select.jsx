import './Select.css'

// A dropdown in the Jaadah style.
//
//   options      the choices, as a list: [{ value: '30', label: 'Last 30 days' }]
//   value        the value of the choice that is currently selected
//   onChange     function called with the new value when the user picks one
//   label        text shown before the dropdown (optional)
//   ariaLabel    hidden description for screen readers; use it when there is
//                no visible label
//   placeholder  text shown while nothing is selected (value is '')
//   size         "md" (normal)  or  "sm" (small, e.g. inside a card header)
function Select({
  options,
  value,
  onChange,
  label,
  ariaLabel,
  placeholder,
  size = 'md',
  className = '',
}) {
  return (
    <label className={`select-field ${className}`}>
      {label && <span className="select-label">{label}</span>}

      <span className="select-wrap">
        <select
          className={`select select-${size}`}
          value={value}
          aria-label={label ? undefined : ariaLabel}
          onChange={(event) => onChange(event.target.value)}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}

          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </span>
    </label>
  )
}

export default Select