import './PageHeader.css'

// The heading at the top of a page: a title, a line under it, and buttons
// or links on the right. Used on Alerts and Recommendation Details.
//
//   title      the page title, e.g. "Alerts"
//   subtitle   the line under the title. Text, or a component such as
//              breadcrumb links (optional)
//   actions    anything to show on the right, e.g. one or more Buttons
//              (optional)
function PageHeader({ title, subtitle, actions, className = '' }) {
  return (
    <header className={`page-header ${className}`}>
      <div className="page-header-text">
        <h1 className="page-header-title">{title}</h1>
        {subtitle && <div className="page-header-subtitle">{subtitle}</div>}
      </div>

      {actions && <div className="page-header-actions">{actions}</div>}
    </header>
  )
}

export default PageHeader