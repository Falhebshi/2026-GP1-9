import { Outlet, useOutletContext } from 'react-router-dom'
import NavBar from './NavBar'

// The frame shared by every page that has the nav bar.
// <Outlet /> is the slot where the current page is placed. It passes on
// the logged-in user from RequireRole, so pages can read it with
// useOutletContext().
function AppLayout() {
  const context = useOutletContext()

  return (
    <>
      <NavBar />
      <main className="page">
        <Outlet context={context} />
      </main>
    </>
  )
}

export default AppLayout