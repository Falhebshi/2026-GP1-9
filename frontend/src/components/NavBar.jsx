import { useState } from 'react'
import { Link, NavLink, useLocation, useNavigate, useOutletContext } from 'react-router-dom'
import Logo from './Logo'
import Notice from './Notice'
import ThemeToggle from './ThemeToggle'
import { HOME_BY_ROLE, logOut } from '../services/authService'
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

  // The logged-in user from RequireRole (none on the /preview gallery)
  const user = useOutletContext()?.user
  const isAdmin = user?.role === 'admin'

  // On Network Overview no intersection is selected yet, so the bar shows
  // only the brand and Log out. Administrators never see the traffic
  // links: they only have the Admin Dashboard.
  const showLinks = !isAdmin && pathname !== '/overview'

  // Shown under the bar when logging out did not reach the server, on the
  // page where it happened only: { message, page }
  const [logoutError, setLogoutError] = useState(null)
  const showLogoutError = logoutError && logoutError.page === pathname

  async function handleLogout() {
    setLogoutError(null)
    try {
      // Ends the session on the server and removes its cookie (PBI 32)
      await logOut()
      navigate('/', { replace: true })
    } catch (error) {
      // Still logged in: stay on the page and say so
      setLogoutError({ message: error.message, page: pathname })
    }
  }

  return (
    <>
      <header className="nav-bar">
        <Link to={isAdmin ? HOME_BY_ROLE.admin : HOME_BY_ROLE.engineer} className="nav-brand">
          <Logo />
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

          <ThemeToggle />
        </nav>
      </header>

      {showLogoutError && (
        <Notice variant="warning" className="nav-notice">
          {logoutError.message}
        </Notice>
      )}
    </>
  )
}

export default NavBar