import { useEffect, useRef, useState } from 'react'

// Shows one part of a page full screen, e.g. the 3D scene with its time and side panel. Used by
// Current Traffic and Traffic Forecast so both behave the same.
//
// It gives back:
//   ref          put it on the element that should fill the screen
//   fullScreen   true while that element is full screen (Esc also leaves it)
//   toggle       enters or leaves full screen
function useFullScreen() {
  const ref = useRef(null)
  const [fullScreen, setFullScreen] = useState(false)

  useEffect(() => {
    const onChange = () => setFullScreen(document.fullscreenElement === ref.current)
    document.addEventListener('fullscreenchange', onChange)
    return () => document.removeEventListener('fullscreenchange', onChange)
  }, [])

  function toggle() {
    if (document.fullscreenElement) document.exitFullscreen()
    else ref.current?.requestFullscreen()
  }

  return { ref, fullScreen, toggle }
}

export default useFullScreen
