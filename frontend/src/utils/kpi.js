// Everything the frontend needs to DISPLAY a KPI result from the backend.
//
// The backend's KPI engine sends KpiResult objects (see the team's
// data_models.md, section 6). The fields used here are:
//
//   kpi          'control_delay', 'level_of_service', 'volume_to_capacity_ratio',
//                'capacity', 'saturation_flow_rate', 'queue_length',
//                'queue_duration', 'queue_storage_ratio', 'throughput'
//   method       'simulation' or 'hcm'
//   unit         's/veh', 'veh/h', 'veh/h/lane', 'ratio', 'm', 'veh', 's', 'grade'
//   value        a number, or null when there is none
//   los_grade    'A' to 'F' (level of service only)
//   status       'ok', 'unavailable' or 'not_applicable'
//   reason       why there is no value (when status is not 'ok')
//   is_shared_value   true when the value was measured on a shared lane
//
// The frontend never calculates a KPI (requirement 36: the same value in
// every view). It only formats what it receives. If the backend changes
// a name or adds a KPI, this file is the one place to update.

// How each KPI is shown
//   label           name on screen
//   decimals        digits after the decimal point
//   higherIsBetter  decides whether a rise is shown as better or worse
//   changeAs        'percent': show a change as "+4%"
//                   'absolute': show it in the KPI's own terms, "+0.03"
export const KPI_DEFINITIONS = {
  control_delay: { label: 'Control delay', decimals: 0, higherIsBetter: false, changeAs: 'percent' },
  level_of_service: { label: 'Level of service', decimals: 0, higherIsBetter: false, changeAs: 'none' },
  volume_to_capacity_ratio: { label: 'v/c ratio', decimals: 2, higherIsBetter: false, changeAs: 'absolute' },
  capacity: { label: 'Capacity', decimals: 0, higherIsBetter: true, changeAs: 'percent' },
  saturation_flow_rate: { label: 'Saturation flow', decimals: 0, higherIsBetter: true, changeAs: 'percent' },
  queue_length: { label: 'Queue length', decimals: 0, higherIsBetter: false, changeAs: 'percent' },
  queue_duration: { label: 'Queue duration', decimals: 0, higherIsBetter: false, changeAs: 'percent' },
  queue_storage_ratio: { label: 'Storage ratio', decimals: 2, higherIsBetter: false, changeAs: 'absolute' },
  throughput: { label: 'Throughput', decimals: 0, higherIsBetter: true, changeAs: 'percent' },
}

// Short tag for where a value came from
export const METHOD_LABELS = {
  simulation: 'Simulated',
  hcm: 'HCM',
}

// What to show instead of a value
export const STATUS_LABELS = {
  unavailable: 'Unavailable',
  not_applicable: 'Not applicable',
}

// Standard limits shown as a warning: v/c above 1.0 means demand is over
// capacity; a storage ratio of 1.0 or more means the queue fills its
// storage and spills back. These are fixed definitions, not calculations.
//   inclusive: true means reaching the limit already counts (1.0 or more)
export const OVER_LIMIT = {
  volume_to_capacity_ratio: { limit: 1, inclusive: false, label: 'over capacity' },
  queue_storage_ratio: { limit: 1, inclusive: true, label: 'queue fills its storage' },
}

// True when a result is at or above its standard limit (see inclusive)
export function isOverLimit(result) {
  const rule = OVER_LIMIT[result?.kpi]
  if (!rule || !hasValue(result)) return false
  return rule.inclusive ? result.value >= rule.limit : result.value > rule.limit
}

// The unit as shown next to a value. A ratio or a grade has none.
export function displayUnit(unit) {
  return unit === 'ratio' || unit === 'grade' ? '' : unit ?? ''
}

// True when the result has a value that can be shown
export function hasValue(result) {
  return result?.status === 'ok' && (result.value != null || result.los_grade != null)
}

// The value as text, without its unit: "1,842", "0.94", "C".
// A result without a value gives "Unavailable" or "Not applicable",
// never 0 (requirement 34).
export function formatKpiValue(result) {
  if (!result) return STATUS_LABELS.unavailable
  if (!hasValue(result)) return STATUS_LABELS[result.status] ?? STATUS_LABELS.unavailable
  if (result.kpi === 'level_of_service') return result.los_grade

  const decimals = KPI_DEFINITIONS[result.kpi]?.decimals ?? 0
  return result.value.toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

// Compares a result with the same KPI for an earlier period, for the
// "+4% vs previous 30 days" line. Gives back the props KpiTile expects:
//   { change, changeUnit, changeTone, changeNote }
// or an empty object when there is nothing to compare.
//   note   text after the change, e.g. "vs prev. 30 days"
export function kpiComparison(current, previous, note = '') {
  const definition = KPI_DEFINITIONS[current?.kpi]
  if (!definition || definition.changeAs === 'none') return {}
  if (!hasValue(current) || !hasValue(previous)) return {}

  let change
  let changeUnit
  if (definition.changeAs === 'percent') {
    if (previous.value === 0) return {}
    change = Math.round(((current.value - previous.value) / previous.value) * 100)
    changeUnit = '%'
  } else {
    const factor = 10 ** definition.decimals
    change = Math.round((current.value - previous.value) * factor) / factor
    changeUnit = ''
  }

  let changeTone = 'neutral'
  let word = 'no change'
  if (change !== 0) {
    const rose = change > 0
    const better = rose === definition.higherIsBetter
    changeTone = better ? 'good' : 'bad'
    word = better ? 'better' : 'worse'
  }

  return {
    change,
    changeUnit,
    changeTone,
    // The word repeats what the color says, for people who cannot see color
    changeNote: [note, word].filter(Boolean).join(' · '),
  }
}

// Everything KpiTile needs from one result, so a page can write
//   <KpiTile label="Avg control delay" {...kpiTileProps(current, previous, 'vs prev. 30 days')} />
export function kpiTileProps(current, previous, note) {
  return {
    value: hasValue(current)
      ? current.kpi === 'level_of_service'
        ? current.los_grade
        : current.value
      : null,
    decimals: KPI_DEFINITIONS[current?.kpi]?.decimals,
    unit: displayUnit(current?.unit),
    status: current?.status,
    reason: current?.reason,
    tag: METHOD_LABELS[current?.method],
    ...kpiComparison(current, previous, note),
  }
}