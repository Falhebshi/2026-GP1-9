// Spells out road names for display: "King Abdullah Rd" -> "King Abdullah Road".
//
// The map's road names come straight from OpenStreetMap, where most are
// abbreviated, and some have quirks: "Rd." and "Rd St" (road + street) both
// mean "Road". The data itself is left as it is; only what is shown changes.
//
//   roadName('Imam Saud Rd × Takhassusi Rd')                  'Imam Saud Road × Takhassusi Road'
//   roadName('Al Shaikh Hasan Bin Abdullah Al Shaikh Rd St')  '... Al Shaikh Road'
//   roadName(null)                                            null
export function roadName(name) {
  if (typeof name !== 'string') return name
  return name
    .replace(/\bRd\.?\s+St\b\.?/g, 'Road') // "Rd St" and "Rd. St"
    .replace(/\bRd\b\.?/g, 'Road') // "Rd" and "Rd."
}
