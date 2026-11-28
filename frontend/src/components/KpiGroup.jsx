import InfoTip from './InfoTip'
import { kpiNotes } from '../utils/kpiNotes'
import './KpiGroup.css'

// A group of KpiTiles with what they share said once instead of on every tile: what the
// changes are compared with and how the values were measured. The two sentences sit behind a
// small info button above the tiles, so they do not take space all the time.
//
//   compared    e.g. "the 15 minutes before" gives "Changes compared with the 15 minutes before"
//   results     the KpiResults shown, for the method line
//               ("All simulated except v/c ratio (HCM)")
//   showNotes   false when the page shows the sentences itself (utils/kpiNotes.js), e.g. in
//               its card header
//   children    the tiles
function KpiGroup({ compared, results = [], showNotes = true, children }) {
  const notes = kpiNotes(compared, results)

  return (
    <div className="kpi-group">
      {showNotes && notes.length > 0 && (
        <div className="kpi-group-info">
          <InfoTip label="About these values" align="end">
            {notes.join('. ')}.
          </InfoTip>
        </div>
      )}
      {children}
    </div>
  )
}

export default KpiGroup
