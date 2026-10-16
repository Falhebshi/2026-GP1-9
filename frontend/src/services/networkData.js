// Data for the Network Traffic Overview page.
//
// Road segment congestion is NOT connected yet: the source (RCRC, TomTom or another feed) is
// decided next sprint, so loadSegments returns null for now and the map shows the plain basemap.
// When the source is ready, only loadSegments has to change. It should resolve to a GeoJSON
// FeatureCollection of LineStrings, one per road segment, with these properties:
//   id          unique id of the segment
//   name        road name, e.g. 'King Fahd Rd'
//   congestion  0 (free flow) to 1 (standstill); sets the heatmap weight
//   level       'low', 'moderate' or 'high'; sets the line colour
//   speed       average speed in km/h (optional, shown on hover)
// It will take the moment to show (an ISO time string, or null for the latest data).
export async function loadSegments() {
  return null
}

// The area the map shows: north Riyadh around King Fahd Rd and the Northern Ring Rd.
export const NETWORK_BOUNDS = [
  [46.585, 24.69],
  [46.73, 24.8],
]

// Intersections in the "Intersections by area" list. Positions are where the two roads cross in
// OpenStreetMap. The district of our study intersection is confirmed (Google Maps); the others are
// the nearest district on the map, so check them before relying on them. Only the study
// intersection has a simulation (simulation: '/current'); the others are listed but not active yet.
export const NETWORK_INTERSECTIONS = [
  {
    id: 'turki_imamsaud',
    name: 'Prince Turki Al-Awwal Rd × Imam Saud Rd',
    area: 'An Nakheel',
    center: [46.633621, 24.735289],
    simulation: '/current',
  },
  {
    id: 'imamsaud_takhassusi',
    name: 'Imam Saud Rd × Takhassusi Rd',
    area: 'Al Muhammadiyah',
    center: [46.64549, 24.74039],
  },
  {
    id: 'kingabdullah_kingfahd',
    name: 'King Abdullah Rd × King Fahd Rd',
    area: 'Ar Rahmaniyah',
    center: [46.66386, 24.7276],
  },
  {
    id: 'turki_urubah',
    name: 'Prince Turki Al-Awwal Rd × Al Urubah Rd',
    area: 'Umm Al Hamam',
    center: [46.65406, 24.70431],
  },
]
