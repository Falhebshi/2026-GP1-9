// Helpers for drawing chart axes.

// Rounds a maximum up to a tidy axis end with tidy steps, e.g. 47 → 0, 10,
// 20, 30, 40, 50. Gives back { max, ticks }.
export function niceScale(maxValue, targetTicks = 4) {
  if (!(maxValue > 0)) return { max: 1, ticks: [0, 0.25, 0.5, 0.75, 1] }

  const rough = maxValue / targetTicks
  const power = 10 ** Math.floor(Math.log10(rough))
  const step = [1, 2, 2.5, 5, 10].map((m) => m * power).find((s) => s >= rough)
  const max = Math.ceil(maxValue / step) * step

  const ticks = []
  for (let value = 0; value <= max + step / 2; value += step) {
    ticks.push(Number(value.toFixed(10))) // avoid 0.30000000000000004
  }
  return { max, ticks }
}

// 4200 → "4.2K", 35 → "35", 0.9 → "0.9"
export function compactNumber(value) {
  if (value >= 1000) return `${Number((value / 1000).toFixed(1))}K`
  return String(Number(value.toFixed(2)))
}