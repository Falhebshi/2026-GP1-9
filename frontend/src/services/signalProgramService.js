// The study intersection's signal program, as the backend writes it from
// the SUMO network (backend/outputs/signal_program.py). Every page that
// shows the plan reads this one file, so the pages always describe the
// plan that SUMO and the KPIs use.
//
//   /data/<intersection>/signal_program.json
//   { intersection_id, network_sha256, control_type, source, cycle_length_s,
//     phases: [{ phase_id, sequence_order, served_movement_ids,
//                green_time_s, yellow_time_s, all_red_time_s }] }

const SIGNAL_PROGRAM_URL = '/data/INT_001/signal_program.json'

// Loaded once and shared by the pages
let loading = null

export function getSignalProgram() {
  if (!loading) {
    loading = fetch(SIGNAL_PROGRAM_URL)
      .then((response) => {
        const isJson = (response.headers.get('content-type') ?? '').includes('json')
        if (!response.ok || !isJson) throw new Error('The signal program could not be loaded.')
        return response.json()
      })
      .catch((error) => {
        loading = null // let the next page try again
        throw error
      })
  }
  return loading
}

const CONTROL_WORDS = { fixed_time: 'Fixed-time' }

// The plan's origin, as the KPI engine labels it (docs/kpi_engine.md, 9.8):
// a plan built for the model is a modelled assumption; an observed plan
// needs no note
const SOURCE_NOTES = { baseline_model: 'modelled', intervention: 'intervention' }

// { control_type: 'fixed_time', cycle_length_s: 225, source: 'baseline_model' }
//   → "Fixed-time, 225 s cycle (modelled)"; no program → undefined ("Unavailable")
export function signalTypeLabel(program) {
  if (!program) return undefined
  const control = CONTROL_WORDS[program.control_type] ?? program.control_type
  const note = SOURCE_NOTES[program.source]
  return `${control}, ${Math.round(program.cycle_length_s)} s cycle${note ? ` (${note})` : ''}`
}
