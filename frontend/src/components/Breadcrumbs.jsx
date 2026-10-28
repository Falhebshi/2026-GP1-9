import { Link } from 'react-router-dom'
import './Breadcrumbs.css'

// Where the page sits, above its title: "Alerts › Queue spillback".
//   items   [{ label, to }], from the top level down. The last item is the
//           current page: it has no link.
function Breadcrumbs({ items, className = '' }) {
  if (!items?.length) return null

  return (
    <nav className={`breadcrumbs ${className}`} aria-label="Breadcrumb">
      <ol className="breadcrumbs-list">
        {items.map((item, index) => {
          const isCurrent = index === items.length - 1
          return (
            <li key={`${item.label}-${index}`} className="breadcrumbs-item">
              {isCurrent || !item.to ? (
                <span className="breadcrumbs-current" aria-current={isCurrent ? 'page' : undefined}>
                  {item.label}
                </span>
              ) : (
                <Link to={item.to} className="breadcrumbs-link">
                  {item.label}
                </Link>
              )}
              {!isCurrent && (
                <svg className="breadcrumbs-separator" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M6 3.5 10.5 8 6 12.5" />
                </svg>
              )}
            </li>
          )
        })}
      </ol>
    </nav>
  )
}

export default Breadcrumbs
