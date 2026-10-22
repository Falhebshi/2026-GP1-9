import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import BrandMark from './BrandMark'
import './NavBar.css'

// The pages shown in the bar. To add or rename a link, edit this list only.
const links = [
  { to: '/overview', label: 'Network Traffic Overview' },
  { to: '/current', label: 'Current Traffic' },
  { to: '/forecast', label: 'Traffic Forecast' },
  { to: '/trends', label: 'Traffic Patterns & Trends' },
  { to: '/alerts', label: 'Alerts' },
]

function NavBar() {
  const navigate = useNavigate()
  const { pathname } = useLocation() // the current URL path, e.g. "/trends"

  // On the Welcome page nobody is logged in yet, so the bar shows only the
  // brand. The page itself has the Log in button.
  const isWelcome = pathname === '/'

  // On Network Overview no intersection is selected yet, and on Welcome
  // nobody is logged in, so the bar shows no page links on either.
  const showLinks = pathname !== '/overview' && !isWelcome

  function handleLogout() {
    // Real logout (ending the session) is added when the backend exists.
    navigate('/')
  }

  return (
    <header className="nav-bar">
      <Link to={isWelcome ? '/' : '/overview'} className="nav-brand">
        <BrandMark size="md" />
        Jaadah
      </Link>

      <nav className="nav-links">
        {showLinks &&
          links.map((link) => (
            <NavLink key={link.to} to={link.to} className="nav-link">
              {link.label}
            </NavLink>
          ))}

        {!isWelcome && (
          <button type="button" className="nav-link" onClick={handleLogout}>
            Log out
          </button>
        )}
      </nav>
    </header>
  )
}

export default NavBar
