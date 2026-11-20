import { useCallback, useEffect, useState } from 'react'

// Light / night mode.
//
//   const { theme, toggleTheme } = useTheme()
//
//   theme         "light" or "dark"
//   toggleTheme   switches to the other one and remembers the choice
//
// The mode lives on <html data-theme="...">, where theme-dark.css looks for
// it. index.html sets it before the page is drawn (saved choice, otherwise
// the computer's setting), so this hook only reads it and changes it.
//
// Code that reads colors itself (e.g. the MapLibre map) can listen for the
// change:  window.addEventListener(THEME_EVENT, (e) => e.detail)  // "light" or "dark"

export const THEME_EVENT = 'jaadah-themechange'
const STORAGE_KEY = 'jaadah-theme' // the same key as in index.html

const systemDark = window.matchMedia('(prefers-color-scheme: dark)')
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)')

function currentTheme() {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'
}

// The user's own choice, or null when they have not picked one
function savedTheme() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved === 'light' || saved === 'dark' ? saved : null
  } catch {
    return null // storage blocked (e.g. private mode)
  }
}

// Switches the page and tells everyone listening. Where the browser can,
// the old and new page cross-fade (one snapshot, no per-element transitions).
function applyTheme(theme) {
  if (currentTheme() === theme) return
  const swap = () => {
    document.documentElement.dataset.theme = theme
    window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: theme }))
  }
  if (document.startViewTransition && !reducedMotion.matches) document.startViewTransition(swap)
  else swap()
}

function useTheme() {
  const [theme, setTheme] = useState(currentTheme)

  useEffect(() => {
    // stay in step when the mode changes anywhere (another toggle, the system)
    const onTheme = (event) => setTheme(event.detail)
    // follow the computer's setting until the user picks a mode themselves
    const onSystem = (event) => {
      if (!savedTheme()) applyTheme(event.matches ? 'dark' : 'light')
    }
    window.addEventListener(THEME_EVENT, onTheme)
    systemDark.addEventListener('change', onSystem)
    return () => {
      window.removeEventListener(THEME_EVENT, onTheme)
      systemDark.removeEventListener('change', onSystem)
    }
  }, [])

  const toggleTheme = useCallback(() => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark'
    try {
      localStorage.setItem(STORAGE_KEY, next)
    } catch {
      // not remembered, but the switch still works for this visit
    }
    applyTheme(next)
  }, [])

  return { theme, toggleTheme }
}

export default useTheme
