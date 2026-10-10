import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import './NavBar.css'

// The pages shown in the bar. To add or rename a link, edit this list only.
const links = [
  { to: '/overview', label: 'Network Traffic Overview' },
  { to: '/current', label: 'Current Traffic' },
  { to: '/forecast', label: 'Traffic Forecast' },
  { to: '/trends', label: 'Traffic Patterns & Trends' },
]

function NavBar() {
  const navigate = useNavigate()
  const { pathname } = useLocation() // the current URL path, e.g. "/trends"

  // On Network Overview no intersection is selected yet, so the bar shows
  // only the brand and Log out.
  const showLinks = pathname !== '/overview'

  function handleLogout() {
    // Real logout (ending the session) is added when the backend exists.
    navigate('/login')
  }

  return (
    <header className="nav-bar">
      <Link to="/overview" className="nav-brand">
        Jaadah
      </Link>

      <nav className="nav-links">
        {showLinks &&
          links.map((link) => (
            <NavLink key={link.to} to={link.to} className="nav-link">
              {link.label}
            </NavLink>
          ))}

        <button type="button" className="nav-link" onClick={handleLogout}>
          Log out
        </button>
      </nav>
    </header>
  )
}

export default NavBar