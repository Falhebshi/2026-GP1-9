import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from './components/AppLayout'
import Welcome from './pages/Welcome'
import Login from './pages/Login'
import NetworkOverview from './pages/NetworkOverview'
import CurrentTraffic from './pages/CurrentTraffic'
import TrafficForecast from './pages/TrafficForecast'
import TrafficTrends from './pages/TrafficTrends'
import ComponentPreview from './pages/ComponentPreview'


// App is the router: it looks at the URL and decides which page to show.
function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Pages WITHOUT the nav bar */}
        <Route path="/" element={<Welcome />} />
        <Route path="/login" element={<Login />} />

        {/* Pages WITH the nav bar (they appear inside AppLayout) */}
        <Route element={<AppLayout />}>
          <Route path="/overview" element={<NetworkOverview />} />
          <Route path="/current" element={<CurrentTraffic />} />
          <Route path="/forecast" element={<TrafficForecast />} />
          <Route path="/trends" element={<TrafficTrends />} />
          <Route path="/preview" element={<ComponentPreview />} />
        </Route>

        {/* Any other URL goes back to the welcome page */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App