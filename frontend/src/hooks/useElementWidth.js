import { useEffect, useRef, useState } from 'react'

// Measures how wide an element is, and measures again whenever it changes
// size (the window is resized, a column wraps). Charts use it to draw at
// their real width, so lines and text stay sharp at any size.
//
//   const [ref, width] = useElementWidth()
//   <div ref={ref}>… draw something width pixels wide …</div>
//
// width is 0 until the element has been measured once.
function useElementWidth() {
  const ref = useRef(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    const element = ref.current
    if (!element) return

    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.round(entry.contentRect.width))
    })
    observer.observe(element)

    return () => observer.disconnect()
  }, [])

  return [ref, width]
}

export default useElementWidth