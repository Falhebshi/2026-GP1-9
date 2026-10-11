import { useEffect, useState } from 'react'

// The clock behind a PlaybackBar: it remembers where the playback is,
// whether it is playing and how fast, and moves the time forward while
// playing. A page calls it once and hands the results to <PlaybackBar>
// and to whatever shows the simulation.
//
//   duration       where the playback ends, in simulated seconds
//   start          where it begins (0 unless you say otherwise)
//   initialSpeed   simulated seconds per real second at the start (10 = x10)
//
// It gives back:
//   time, setTime         where the playback is, in simulated seconds. While
//                         playing it is not a whole number (e.g. 12.4).
//   playing, setPlaying   true while playing. Pressing play at the end
//                         begins again from the start.
//   speed, setSpeed       the current speed
//   playFrom(time)        jump to a time and play from there
//
// This is a stand-in until the real simulation playback exists. When it
// does, this file is the one place to change: the pages and PlaybackBar
// keep working as long as it gives back the same names.
function usePlayback({ duration, start = 0, initialSpeed = 10 }) {
  const [time, setTime] = useState(start)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(initialSpeed)

  // While playing, move the time forward ten times a second.
  // Each step measures how much REAL time passed since the previous one and
  // multiplies it by the speed, so x10 means exactly 10 simulated seconds
  // per real second, even when the browser is busy.
  // useEffect starts this when one of the values in the list at the bottom
  // changes, and the function it returns stops the previous one first.
  useEffect(() => {
    if (!playing) return

    let previous = performance.now() // real time of the previous step, in ms

    const timer = setInterval(() => {
      const now = performance.now()
      const realSeconds = (now - previous) / 1000
      previous = now
      setTime((current) => Math.min(current + realSeconds * speed, duration))
    }, 100)

    return () => clearInterval(timer)
  }, [playing, speed, duration])

  // Reached the end: stop there, so the final state stays on screen
  useEffect(() => {
    if (playing && time >= duration) setPlaying(false)
  }, [playing, time, duration])

  function changePlaying(shouldPlay) {
    if (shouldPlay && time >= duration) setTime(start)
    setPlaying(shouldPlay)
  }

  function playFrom(newTime) {
    setTime(newTime)
    setPlaying(true)
  }

  return {
    time,
    setTime,
    playing,
    setPlaying: changePlaying,
    speed,
    setSpeed,
    playFrom,
  }
}

export default usePlayback