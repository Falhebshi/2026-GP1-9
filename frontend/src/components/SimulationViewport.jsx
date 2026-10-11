import Badge from './Badge'
import EmptyState from './EmptyState'
import './SimulationViewport.css'

// The frame a simulation (or the map) is shown in: a bordered box with an
// optional title, floating panels on top, and a strip along the bottom.
// Used on Current Traffic, Traffic Forecast and Recommendation Details.
//
// The viewport does not draw the simulation. Whatever you put between
// <SimulationViewport> and </SimulationViewport> fills the box: the map,
// a deck.gl view, or an <iframe>. With nothing inside, it shows an empty
// placeholder, so pages can be laid out before the simulation exists.
//
//   title       heading above the box, e.g. "Baseline" (optional)
//   height      height of the box in pixels (360 unless you say otherwise)
//   overlay     anything to float in the top left corner, e.g. a
//               <LocationInfoCard floating />
//   timeLabel   the time being shown, as text, in the top right corner
//   mode        "live", "historical" or "forecast": adds a matching badge
//               next to the time, so it is always clear what is on screen
//   footer      anything to show in a strip along the bottom, e.g. a
//               <PlaybackBar />
//   error       text shown instead of the simulation when it did not run
function SimulationViewport({
  title,
  height = 360,
  overlay,
  timeLabel,
  mode,
  footer,
  error,
  className = '',
  children,
}) {
  const badge = MODES[mode]

  return (
    <section className={`viewport ${className}`}>
      {title && (
        <header className="viewport-header">
          <h3>{title}</h3>
        </header>
      )}

      <div className="viewport-stage" style={{ height }}>
        {error && (
          <div className="viewport-message">
            <EmptyState variant="error" title="Simulation did not run">
              {error}
            </EmptyState>
          </div>
        )}

        {!error && children && <div className="viewport-content">{children}</div>}

        {!error && !children && (
          <div className="viewport-placeholder">
            <p className="viewport-placeholder-title">Simulation view</p>
            <p>Nothing to show yet</p>
          </div>
        )}

        {overlay && <div className="viewport-overlay">{overlay}</div>}

        {/* The time and badge describe the simulation, so they are hidden
            when there is none */}
        {!error && (timeLabel || badge) && (
          <div className="viewport-status">
            {timeLabel && (
              <>
                <span className="viewport-status-label">Simulation time</span>
                <span className="viewport-status-time">{timeLabel}</span>
              </>
            )}
            {badge && <Badge variant={badge.variant}>{badge.text}</Badge>}
          </div>
        )}
      </div>

      {footer && <div className="viewport-footer">{footer}</div>}
    </section>
  )
}

// The badge for each mode. Live and Historical use the same colors as the
// Historical Timeline.
const MODES = {
  live: { text: 'Live', variant: 'success' },
  historical: { text: 'Historical', variant: 'warning' },
  forecast: { text: 'Forecast', variant: 'count' },
}

export default SimulationViewport