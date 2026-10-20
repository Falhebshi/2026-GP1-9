// Reads a color from the theme in index.css, for libraries that need the actual value instead of
// var(--name), such as the MapLibre map styles.
//   themeColor('--congestion-low')  ->  '#2e8b70'
export function themeColor(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim()
}
