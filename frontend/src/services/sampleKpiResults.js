// Builds SAMPLE KpiResult objects for the Current Traffic and Traffic Forecast services, in the
// same shape the backend's KPI engine will send (data_models.md, section 6). Only the services
// use this file; pages show the results through src/utils/kpi.js. When the backend is
// connected, this file is no longer needed.
//
//   element    where the value belongs: { level: 'intersection', id: 'INT_001' },
//              { level: 'approach', id: 'APP_E' } or { level: 'movement', id: 'MOV_E_W' }
//   interval   [interval_start, interval_end] as ISO strings

const UNITS = {
  control_delay: 's/veh',
  level_of_service: 'grade',
  volume_to_capacity_ratio: 'ratio',
  capacity: 'veh/h',
  saturation_flow_rate: 'veh/h',
  queue_length: 'm',
  queue_duration: 's',
  queue_storage_ratio: 'ratio',
  throughput: 'veh/h',
}

// HCM results are calculated; the others are measured in the simulation
const METHODS = {
  volume_to_capacity_ratio: 'hcm',
  capacity: 'hcm',
  saturation_flow_rate: 'hcm',
}

const SCENARIO_ID = 'SCN_SAMPLE_BASELINE'
const RUN_IDS = ['RUN_SAMPLE_1']

// One KPI result with a value. For level of service the value is the grade, e.g. 'D'.
export function sampleResult(kpi, value, element, interval, extra = {}) {
  const method = METHODS[kpi] ?? 'simulation'
  return {
    kpi,
    method,
    unit: UNITS[kpi],
    level: element.level,
    [`${element.level}_id`]: element.id,
    interval_start: interval[0],
    interval_end: interval[1],
    value: kpi === 'level_of_service' ? null : value,
    los_grade: kpi === 'level_of_service' ? value : null,
    status: 'ok',
    reason: null,
    input_origins: method === 'hcm' ? ['modelled_assumption', 'simulated'] : ['simulated'],
    scenario_id: SCENARIO_ID,
    run_ids: method === 'hcm' ? [] : RUN_IDS,
    is_shared_value: false,
    ...extra,
  }
}

// A KPI that applies but has no value, with the reason shown to the user
export function unavailableResult(kpi, element, interval, reason) {
  return { ...sampleResult(kpi, null, element, interval), los_grade: null, status: 'unavailable', reason }
}

// A KPI that does not apply to this element, e.g. LOS for an uncontrolled right turn
export function notApplicableResult(kpi, element, interval, reason) {
  return { ...sampleResult(kpi, null, element, interval), los_grade: null, status: 'not_applicable', reason }
}

// The 15-minute interval that ended most recently, as [start, end]
export function latestInterval(now = Date.now()) {
  const quarter = 15 * 60 * 1000
  const end = Math.floor(now / quarter) * quarter
  return [new Date(end - quarter).toISOString(), new Date(end).toISOString()]
}
