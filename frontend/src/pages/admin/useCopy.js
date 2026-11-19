import { useEffect, useRef, useState } from 'react'

// Copies a text to the clipboard for a Copy button (ADM-01, ADM-05).
//
//   const { copyState, copy } = useCopy(password)
//
//   copyState   '' | 'copied' | 'failed'; "copied" shows "Copied" on the
//               button for 2 seconds; "failed" means the browser refused
//               (e.g. not allowed on this page), so the user copies it
//               themselves
//   copy()      copies the text

// How long "Copied" stays on the button
const COPIED_MS = 2000

export default function useCopy(text) {
  const [copyState, setCopyState] = useState('')
  const timer = useRef(null)

  // Stop the timer if the button goes away (e.g. after Confirm)
  useEffect(() => () => clearTimeout(timer.current), [])

  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      setCopyState('copied')
    } catch {
      setCopyState('failed')
    }
    clearTimeout(timer.current)
    timer.current = setTimeout(() => setCopyState(''), COPIED_MS)
  }

  return { copyState, copy }
}

// The message to show when copying failed
export const COPY_FAILED = 'Copying is not available here. Select the password and copy it yourself.'
