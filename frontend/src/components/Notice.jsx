import './Notice.css'

// A one-line message across the top of a page or section.
//
//   variant   "warning"  amber, e.g. "Sample data for layout only"
//             "info"     lavender, for neutral information
//
// The text between <Notice> and </Notice> is the message.
function Notice({ variant = 'info', className = '', children }) {
  return (
    <div className={`notice notice-${variant} ${className}`} role="status">
      {children}
    </div>
  )
}

export default Notice