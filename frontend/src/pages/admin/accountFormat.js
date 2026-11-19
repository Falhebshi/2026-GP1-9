// How account details are shown on the Admin Dashboard, used by the list
// and the details panel so they always match (NFR-05: consistent names).

import { RIYADH_TIME_ZONE } from '../../utils/riyadhTime'

// The words and Badge colours for each account status
export const STATUS_LABELS = { active: 'Active', inactive: 'Inactive' }
export const STATUS_VARIANTS = { active: 'success', inactive: 'neutral' }

// "2026-11-18T06:00:00+00:00" → "18 Nov 2026", the date in Riyadh
export function createdDate(isoTime) {
  return new Date(isoTime).toLocaleDateString('en-GB', {
    timeZone: RIYADH_TIME_ZONE,
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}
