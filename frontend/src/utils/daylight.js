// Works out how dark it is at a place and time, so the 3D scene can show day, dusk or night.
// Uses the NOAA sun position formula, which is accurate to a few minutes.

const RAD = Math.PI / 180

// Sun height above the horizon in degrees, at `date` for [longitude, latitude]
export function sunElevation(date, [longitude, latitude]) {
  const day = date.getTime() / 86400000 + 2440587.5 - 2451545.0 // days since 1 Jan 2000, 12:00 UTC
  const meanLong = (280.46 + 0.9856474 * day) % 360
  const anomaly = (357.528 + 0.9856003 * day) * RAD
  const eclLong = (meanLong + 1.915 * Math.sin(anomaly) + 0.02 * Math.sin(2 * anomaly)) * RAD
  const obliquity = (23.439 - 0.0000004 * day) * RAD
  const declination = Math.asin(Math.sin(obliquity) * Math.sin(eclLong))
  const rightAsc = Math.atan2(Math.cos(obliquity) * Math.sin(eclLong), Math.cos(eclLong))
  const siderealDeg = (280.46061837 + 360.98564736629 * day + longitude) % 360
  const hourAngle = siderealDeg * RAD - rightAsc
  const lat = latitude * RAD
  return (
    Math.asin(
      Math.sin(lat) * Math.sin(declination) +
        Math.cos(lat) * Math.cos(declination) * Math.cos(hourAngle),
    ) / RAD
  )
}

// 0 in daylight, 1 at night. In between during dusk and dawn: it starts getting darker when the
// sun is 3 degrees above the horizon and is fully dark at -6 degrees (end of civil twilight),
// so evening comes in gradually instead of switching at once.
export function darkness(date, lonLat) {
  const elevation = sunElevation(date, lonLat)
  return Math.min(1, Math.max(0, (3 - elevation) / 9))
}
