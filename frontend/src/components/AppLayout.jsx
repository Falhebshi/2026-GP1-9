import { Outlet } from 'react-router-dom'
import NavBar from './NavBar'

// The frame shared by every page that has the nav bar.
// <Outlet /> is the slot where the current page is placed.
function AppLayout() {
  return (
    <>
      <NavBar />
      <main className="page">
        <Outlet />
      </main>
    </>
  )
}

export default AppLayout