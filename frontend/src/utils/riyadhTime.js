// Jaadah's data is in Riyadh time, so dates and hours are shown in Riyadh time whatever time zone
// the laptop is set to. Riyadh is UTC+3 all year (no daylight saving).
//
//   riyadhParts(ms)          { day: 'YYYY-MM-DD', hour, minute } of a moment in Riyadh
//   riyadhTime(day, hour)    the ISO time of that Riyadh day and hour, e.g. '2026-11-14T08:00:00+03:00'
//   RIYADH_TIME_ZONE         for toLocaleDateString / toLocaleTimeString ({ timeZone })

export const RIYADH_TIME_ZONE = 'Asia/Riyadh'

const RIYADH_OFFSET = 3 * 60 * 60 * 1000
const pad = (n) => String(n).padStart(2, '0')

export function riyadhParts(ms) {
  const riyadh = new Date(ms + RIYADH_OFFSET)
  return {
    day: riyadh.toISOString().slice(0, 10),
    hour: riyadh.getUTCHours(),
    minute: riyadh.getUTCMinutes(),
  }
}

export function riyadhTime(day, hour, minute = 0) {
  return `${day}T${pad(hour)}:${pad(minute)}:00+03:00`
}
