import './Button.css'

// A clickable button in the Jaadah style.
//
//   variant   "primary" (filled, the main action), "secondary" (outlined) or
//             "danger" (filled red, for an action that cannot be undone,
//             such as deleting)
//   size      "md" (normal)  or  "sm" (small, e.g. Latest / Live)
//   children  Whatever you put between the opening and closing tags
// ...props    Anything else you pass (onClick, disabled, type="submit" ...) is handed
//             straight to the real <button>.
function Button({
  variant = 'primary',
  size = 'md',
  className = '',
  children,
  ...props
}) {
  const classes = `btn btn-${variant} btn-${size} ${className}`

  return (
    <button type="button" className={classes} {...props}>
      {children}
    </button>
  )
}

export default Button