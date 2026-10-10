import './EmptyState.css'

// A dashed box shown in place of content that is missing.
//
//   title     short bold line (optional)
//   variant   "info"   nothing to show: no alerts, no data for this period
//             "error"  something failed: the simulation did not run
//
// The text between <EmptyState> and </EmptyState> is the message.
function EmptyState({ title, variant = 'info', className = '', children }) {
  return (
    <div
      className={`empty-state empty-state-${variant} ${className}`}
      // Tells screen readers to announce the message when it appears
      role={variant === 'error' ? 'alert' : 'status'}
    >
      {title && <p className="empty-state-title">{title}</p>}
      {children && <p>{children}</p>}
    </div>
  )
}

export default EmptyState