import { useEffect, useState } from 'react'

// Measures how wide an element is, and measures again whenever it changes
// size (the window is resized, a column wraps). Charts use it to draw at
// their real width, so lines and text stay sharp at any size.
//
//   const [ref, width] = useElementWidth()
//   <div ref={ref}>… draw something width pixels wide …</div>
//
// width is 0 until the element has been measured once.
//
// ref is a callback ref, so the element is measured even when it appears
// after the first render (a chart that first showed an empty message).
function useElementWidth() {
  const [element, ref] = useState(null)
  const [width, setWidth] = useState(0)

  useEffect(() => {
    if (!element) return

    const observer = new ResizeObserver(([entry]) => {
      setWidth(Math.round(entry.contentRect.width))
    })
    observer.observe(element)

    return () => observer.disconnect()
  }, [element])

  return [ref, width]
}

export default useElementWidth