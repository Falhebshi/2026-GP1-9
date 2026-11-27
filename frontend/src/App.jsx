import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import RequireRole from './components/RequireRole'
import Welcome from './pages/Welcome'
import Login from './pages/Login'
import NetworkOverview from './pages/NetworkOverview'
import CurrentTraffic from './pages/CurrentTraffic'
import TrafficTrends from './pages/TrafficTrends'
import ComponentPreview from './pages/ComponentPreview'
import PlannedForRelease2 from './pages/PlannedForRelease2'
import AdminDashboard from './pages/AdminDashboard'


// App is the router: it looks at the URL and decides which page to show.
function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Pages WITHOUT the nav bar */}
        <Route path="/" element={<Welcome />} />
        <Route path="/login" element={<Login />} />

        {/* Traffic pages: logged-in traffic engineers only (RequireRole).
            They appear inside AppLayout, which adds the nav bar. */}
        <Route element={<RequireRole role="engineer" />}>
          <Route element={<AppLayout />}>
            <Route path="/overview" element={<NetworkOverview />} />
            <Route path="/current" element={<CurrentTraffic />} />
            {/* Traffic Forecast and Alerts come in Release 2: their tabs stay, their pages say so.
                The Release 2 pages are in pages/TrafficForecast.jsx, Alerts.jsx, AlertDetails.jsx
                and RecommendationDetails.jsx */}
            <Route path="/forecast" element={<PlannedForRelease2 title="Traffic Forecast" />} />
            <Route path="/trends" element={<TrafficTrends />} />
            <Route path="/alerts" element={<PlannedForRelease2 title="Alerts" />} />
            <Route path="/alerts/*" element={<Navigate to="/alerts" replace />} />
          </Route>
        </Route>

        {/* Admin pages: logged-in administrators only */}
        <Route element={<RequireRole role="admin" />}>
          <Route element={<AppLayout />}>
            <Route path="/admin" element={<AdminDashboard />} />
          </Route>
        </Route>

        {/* The component gallery for development: no login needed */}
        <Route element={<AppLayout />}>
          <Route path="/preview" element={<ComponentPreview />} />
        </Route>

        {/* Any other URL goes back to the welcome page */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
