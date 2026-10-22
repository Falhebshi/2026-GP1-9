// Small helpers for showing dates and times.
//
// Times from the backend are Riyadh time with the offset written in,
// e.g. "2026-10-14T17:15:00+03:00". These helpers read the text directly,
// so the time shown is always Riyadh time, whatever the viewer's computer
// is set to.

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

// "2026-09-15" → "15 Sep"
export function shortDate(dateText) {
  const [, month, day] = dateText.split('-')
  return `${Number(day)} ${MONTHS[Number(month) - 1]}`
}

// "2026-09-15" → "Tue 15 Sep"
export function dayAndDate(dateText) {
  const [year, month, day] = dateText.split('-').map(Number)
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay()
  return `${WEEKDAYS[weekday]} ${day} ${MONTHS[month - 1]}`
}

// "2026-10-14T17:15:00+03:00" → "17:15"
export function timeOf(timestamp) {
  return timestamp?.slice(11, 16) ?? ''
}

// Two timestamps → "17:15–17:30"
export function timeRange(start, end) {
  return `${timeOf(start)}–${timeOf(end)}`
}