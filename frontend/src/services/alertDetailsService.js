// Where the Alert Details page gets its data.
//
// For now it returns FAKE data. When the backend is ready, only the inside
// of getAlertDetails() changes (it will fetch from the server); the page
// stays the same, as long as the data keeps this shape.
//
// PROPOSED CONTRACT: agree it with the backend team before relying on it.
//
//   getAlertDetails(problemId)
//
//   problemId identifies the detected traffic problem behind an alert, not
//   an intervention: one problem can have zero, one or several recommended
//   interventions. The Alerts page links to /alerts/<problemId>.
//
//   {
//     problem: {
//       problem_id: 1,
//       alert_type: 'current',          'current', 'forecast' or 'pattern'
//       title: 'Queue spillback',
//       description: 'The left-turn queue ...',
//       intersection_id: 'INT_001',
//       intersection_name: 'Prince Turki Al-Awwal Rd × Imam Saud Rd',
//       approach_id: 'APP_N',
//       location: 'North approach',
//       interval_start: '2026-10-14T07:45:00+03:00',   the period the
//       interval_end: '2026-10-14T08:00:00+03:00',     KPIs describe
//       period_label: 'Morning peak',   a short name for the period (not
//                                       Scenario.time_context, which is
//                                       historical, current or forecast)
//       detected_at: '2026-10-14T08:01:00+03:00',      when the problem was
//                                       detected, after its period ends
//                                       (forecast: when it is expected)
//       forecast_outlook: 'Congestion is expected to ...'   one sentence from
//                                       the forecast model, or null
//       indicators: ['Delay at LOS F (84 s/veh)', ...]   the conditions the
//                                       problem was flagged for, in words
//       triggered_by: [                 the KPIs among them, so the page can
//         { kpi, level, unit },         mark those tiles; unit only when a
//       ],                              KPI comes in two (queue length)
//       recurrence: 'Weekdays ...',     pattern alerts only: when and how
//                                       often it occurs (PBI 25); else null
//       recurrence_days: [              pattern alerts only: each recent
//         { date: '2026-10-07',         weekday (Sunday to Thursday) at the
//           occurred: true,             problem's period, whether the problem
//           value, los_grade,           recurred that day, and its control
//           status, reason },           delay and LOS then; else null
//       ],
//       history: {                      how the problem developed: one KPI
//         kpi: 'control_delay',         of the problem approach (control
//         method: 'simulation',         delay this sprint: storage ratios
//         unit: 's/veh',                need storage lengths, not known yet)
//         points: [                     one per 15-minute interval (the KPI
//           { interval_start,           engine's analysis interval), oldest
//             interval_end,             first: the past two hours, then the
//             kind, value, los_grade,   forecast at 15, 30, 45 and 60 min
//             status, reason },         (PBI 18). kind: 'past' or
//         ],                            'forecast'. value is null when status
//       },                              is not 'ok', with the engine's reason
//     },
//
//     baseline: {                      the period without any change (for
//       scenario_id: 'SCN_BASE_001',   a forecast alert, the predicted
//       cycle_length_s: 120,           conditions); its current signal
//                                      cycle, or null
//       kpis: [KpiResult, ...],        see data_models.md, KpiResult
//     },
//
//     recommendations: [               already sorted and ranked by the backend
//       {
//         recommendation_id: 'REC_001_A',
//         rank: 1,                     1 = best. null when it could not be
//                                      ranked (its simulation did not finish)
//         title: 'Extend the north left-turn green',
//         category: 'signal_timing',   'signal_timing' (green split),
//                                      'cycle_length' or 'phase_sequence':
//                                      signal timing only in this version
//         summary: 'One sentence on what the option does.',
//         rank_reason: 'Why it is ranked here.',
//         cycle_length_s: 120,         the signal cycle with this option,
//                                      or null when not known
//         comparisons: [KpiComparison, ...],   this option against the
//                                      baseline, one per KPI (see below)
//         scenario_id: 'SCN_INT_001_A',   its intervention scenario
//         status: 'ok',                'ok' or 'unavailable'
//         reason: null,                why it is unavailable
//         kpis: [KpiResult, ...],      same KPIs, levels and period as the
//                                      baseline, from the intervention runs
//       },
//     ],
//
//     isSample: true,                  true only while this is fake
//   }
//
// Every KpiResult the page reads, for the baseline and for each option
// (kpi_engine.md; method in brackets):
//   approach (approach_id = problem.approach_id)
//     control_delay, level_of_service, queue_length in 'm' and in 'veh',
//     queue_storage_ratio, queue_duration, throughput   (simulation)
//     volume_to_capacity_ratio                          (hcm)
//   intersection (intersection_id = problem.intersection_id)
//     control_delay, level_of_service, throughput       (simulation)
//     volume_to_capacity_ratio: the critical v/c, Xc    (hcm)
// Simulation results average several runs and carry standard_deviation
// (none for a grade); HCM results have no runs and no standard deviation.
// Simulation results of an approach with an uncontrolled right-turn slip,
// and of the intersection, carry uncontrolled_movements: 'included'.
//
// KpiComparison: one KPI of an intervention against its baseline,
// worked out by the KPI engine from matched runs (kpi_engine.md 12.4).
// The field names are PROPOSED; confirm them with the KPI engine owner.
//   { kpi, method, unit, level, approach_id | intersection_id,
//     interval_start, interval_end,
//     status, reason,                'ok', 'unavailable' or 'not_applicable'
//     baseline_mean,                 over the pairs used
//     change,                        mean of (intervention − baseline)
//     change_standard_deviation,     across the pairs; null for HCM
//     percent_change,                change ÷ baseline_mean × 100; null
//                                    when baseline_mean is 0
//     baseline_grade,                level of service only: both grades,
//     intervention_grade,            from the delay comparison
//     used_pairs, pair_count,        pairs used, and pairs in the set
//     is_partial_sample }            true when some pairs were left out
//
// The frontend never calculates a KPI or a change: the backend sends every
// value, comparison and the ranking. The page only shows them.

// Gives back the problem, the baseline and the ranked recommendations.
// It is "async" because the real version will wait for the server; the
// fake version waits a moment to behave the same way.
export async function getAlertDetails(problemId) {
  await wait(300)

  // FOR TESTING ONLY: add one of these to the page address
  //   ?demo=empty   a problem with no recommendation
  //   ?demo=error   the service is not responding
  const demo = new URLSearchParams(window.location.search).get('demo')
  if (demo === 'error') throw new Error('The alert details service is not responding.')

  // Later: return (await fetch(`/api/problems/${problemId}/recommendations`)).json()
  const found = FAKE_DATA[problemId]
  if (!found) throw new Error('This problem could not be found. It may have been resolved.')

  const data = build(found)
  if (demo === 'empty') return { ...data, recommendations: [] }
  return data
}

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

// ---- Fake data ------------------------------------------------------------
// Everything below this line is deleted when the backend is connected.
//
// To keep the list short, each scenario is written as six numbers and
// turned into full KpiResult objects by build():
//   [approach delay s/veh, approach LOS, queue m, storage ratio,
//    intersection delay s/veh, intersection LOS]
// null in place of the six numbers means the simulation did not finish.

const INTERSECTION = {
  intersection_id: 'INT_001',
  intersection_name: 'Prince Turki Al-Awwal Rd × Imam Saud Rd',
}

const DID_NOT_FINISH =
  'The simulation for this option did not finish, so its expected impact is unavailable.'

const FAKE_DATA = {
  1: {
    problem: {
      alert_type: 'current',
      title: 'Queue spillback',
      description:
        'The left-turn queue on the north approach is longer than its storage bay and is blocking the through lanes beside it.',
      approach_id: 'APP_N',
      location: 'North approach',
      interval_start: '2026-10-14T07:45:00+03:00',
      interval_end: '2026-10-14T08:00:00+03:00',
      period_label: 'Morning peak',
      detected_at: '2026-10-14T08:01:00+03:00',
      forecast_outlook: 'Congestion on the north approach is expected to stay high until about 08:30.',
    },
    indicators: ['Delay at LOS F (84 s/veh)', 'Queue reaching the end of the left-turn lanes', 'Delay rising for 4 intervals in a row'],
    triggered_by: [{ kpi: 'control_delay', level: 'approach' }, { kpi: 'queue_length', level: 'approach', unit: 'm' }],
    baseline: [84, 'F', 212, 1.31, 52, 'D'],
    recommendations: [
      {
        title: 'Extend the north left-turn green',
        category: 'signal_timing',
        summary: 'Gives the north left turn more green time within the current cycle.',
        rank_reason:
          'Clears the spillback with the smallest change, and lowers delay for the intersection as a whole.',
        kpis: [49, 'D', 148, 0.92, 47, 'D'],
      },
      {
        title: 'Lengthen the cycle to 140 s',
        category: 'cycle_length',
        summary: 'Adds 20 s to the cycle and gives most of it to the north left turn.',
        rank_reason:
          'Also keeps the queue inside its bay, but only just, and every other approach waits longer.',
        kpis: [58, 'E', 171, 0.98, 55, 'D'],
      },
      {
        title: 'Add a second north left-turn phase',
        category: 'phase_sequence',
        summary: 'Serves the north left turn twice per cycle, before and after the through movement.',
        rank_reason:
          'Shortens the queue, but it still reaches past the bay in the busiest 15 minutes.',
        kpis: [62, 'E', 182, 1.04, 50, 'D'],
      },
      {
        title: 'Move green from the east left turn to the north',
        category: 'signal_timing',
        summary: 'Takes 6 s of green from the east left turn and gives it to the north left turn.',
        rank_reason: null,
        kpis: null,
      },
    ],
  },

  2: {
    problem: {
      alert_type: 'current',
      title: 'Low average speed',
      description:
        'Through traffic on the east approach is moving well below its usual speed for this time of day.',
      approach_id: 'APP_E',
      location: 'East approach',
      interval_start: '2026-10-14T13:45:00+03:00',
      interval_end: '2026-10-14T14:00:00+03:00',
      period_label: 'Early afternoon',
      detected_at: '2026-10-14T14:01:00+03:00',
      forecast_outlook: 'Speeds on the east approach are expected to recover after 14:30.',
    },
    indicators: ['Average speed below the usual for this time', 'Delay at LOS E (61 s/veh)'],
    triggered_by: [{ kpi: 'control_delay', level: 'approach' }],
    baseline: [61, 'E', 164, 0.82, 44, 'D'],
    recommendations: [
      {
        title: 'Rebalance the east–west green',
        category: 'signal_timing',
        summary: 'Moves green time from the west through movement to the east, where demand is higher.',
        rank_reason: 'Lowers east delay the most, with little effect on the rest of the intersection.',
        kpis: [43, 'D', 121, 0.61, 41, 'D'],
      },
      {
        title: 'Shorten the cycle to 100 s',
        category: 'cycle_length',
        summary: 'Serves every approach more often, so queues have less time to build.',
        rank_reason: 'Helps the east approach less than option 1, but spreads the benefit to all approaches.',
        kpis: [50, 'D', 139, 0.69, 40, 'D'],
      },
    ],
  },

  3: {
    problem: {
      alert_type: 'forecast',
      title: 'High V/C ratio',
      description: 'Demand on the west approach is expected to exceed its capacity within 25 minutes.',
      approach_id: 'APP_W',
      location: 'West approach',
      interval_start: '2026-10-14T14:30:00+03:00',
      interval_end: '2026-10-14T14:45:00+03:00',
      period_label: 'Afternoon',
      detected_at: '2026-10-14T14:30:00+03:00',
      forecast_outlook: 'Demand on the west approach is expected to exceed capacity from about 14:30.',
    },
    indicators: ['Forecast v/c above 1.0 within 30 minutes', 'Delay rising for 3 intervals in a row'],
    triggered_by: [{ kpi: 'control_delay', level: 'approach' }],
    baseline: [72, 'E', 216, 1.08, 49, 'D'],
    recommendations: [
      {
        title: 'Extend the west through green',
        category: 'signal_timing',
        summary: 'Adds green time to the west through movement before demand peaks.',
        rank_reason: 'Keeps the west approach below capacity for the whole forecast window.',
        kpis: [52, 'D', 142, 0.71, 47, 'D'],
      },
      {
        title: 'Lengthen the cycle to 140 s',
        category: 'cycle_length',
        summary: 'Adds 20 s to the cycle, shared across all phases.',
        rank_reason: 'Raises capacity on every approach, but delay rises for the intersection as a whole.',
        kpis: [63, 'E', 166, 0.84, 53, 'D'],
      },
    ],
  },

  4: {
    problem: {
      alert_type: 'forecast',
      title: 'Queue buildup',
      description: 'The queue on the south approach is expected to reach its storage limit within 12 minutes.',
      approach_id: 'APP_S',
      location: 'South approach',
      interval_start: '2026-10-14T14:15:00+03:00',
      interval_end: '2026-10-14T14:30:00+03:00',
      period_label: 'Afternoon',
      detected_at: '2026-10-14T14:15:00+03:00',
      forecast_outlook: 'The south queue is expected to reach its storage limit within 15 minutes.',
    },
    indicators: ['Forecast queue reaching the end of the south lanes', 'Queue growing for 3 intervals in a row'],
    triggered_by: [{ kpi: 'queue_length', level: 'approach', unit: 'm' }],
    baseline: [57, 'E', 96, 0.91, 46, 'D'],
    recommendations: [
      {
        title: 'Extend the south green',
        category: 'signal_timing',
        summary: 'Gives the south approach more green time while its queue is growing.',
        rank_reason: 'Keeps the queue well inside its storage for the forecast window.',
        kpis: [41, 'D', 64, 0.61, 45, 'D'],
      },
    ],
  },

  5: {
    problem: {
      alert_type: 'pattern',
      title: 'Recurring low speed',
      description: 'Through traffic on the east approach slows down on most weekday afternoons.',
      approach_id: 'APP_E',
      location: 'East approach',
      interval_start: '2026-10-14T17:00:00+03:00',
      interval_end: '2026-10-14T17:15:00+03:00',
      period_label: 'Weekday evening peak',
      recurrence: 'Weekdays 16:00–18:00, on 3 of the last 5 weekdays',
      detected_at: '2026-10-07T17:15:00+03:00',
      forecast_outlook: null,
    },
    indicators: ['Low speed on 3 of the last 5 weekdays', 'Delay at LOS E in the evening peak'],
    triggered_by: [{ kpi: 'control_delay', level: 'approach' }],
    baseline: [66, 'E', 171, 0.86, 47, 'D'],
    recommendations: [
      {
        title: 'Afternoon timing plan for the east approach',
        category: 'signal_timing',
        summary: 'A separate weekday 16:00–18:00 timing plan with more green for the east approach.',
        rank_reason: 'Targets the hours when the problem repeats, and leaves other hours unchanged.',
        kpis: [45, 'D', 128, 0.64, 43, 'D'],
      },
      {
        title: 'Rebalance the east–west green all day',
        category: 'signal_timing',
        summary: 'A smaller change to the current plan, used at all hours.',
        rank_reason: 'Easier to apply, but helps less in the afternoon peak.',
        kpis: [55, 'D', 149, 0.75, 45, 'D'],
      },
    ],
  },

  6: {
    problem: {
      alert_type: 'current',
      title: 'Signal timing issue',
      description: 'The south approach is getting more green time than its demand needs, while other approaches queue.',
      approach_id: 'APP_S',
      location: 'South approach',
      interval_start: '2026-10-14T12:45:00+03:00',
      interval_end: '2026-10-14T13:00:00+03:00',
      period_label: 'Midday',
      detected_at: '2026-10-14T13:01:00+03:00',
      forecast_outlook: null,
    },
    indicators: ['South green time unused for several cycles', 'Long queues on the other approaches'],
    triggered_by: [{ kpi: 'control_delay', level: 'intersection' }],
    baseline: [38, 'D', 41, 0.39, 51, 'D'],
    recommendations: [
      {
        title: 'Shorten the south green',
        category: 'signal_timing',
        summary: 'Moves unused south green time to the approaches that need it.',
        rank_reason: 'Lowers delay for the intersection as a whole with a small timing change.',
        kpis: [45, 'D', 58, 0.55, 42, 'D'],
      },
    ],
  },
  7: {
    problem: {
      alert_type: 'pattern',
      title: 'Recurring queue buildup',
      description: 'The left-turn queue on the north approach grows past its storage bay on most weekday mornings.',
      approach_id: 'APP_N',
      location: 'North approach',
      interval_start: '2026-10-14T07:45:00+03:00',
      interval_end: '2026-10-14T08:00:00+03:00',
      period_label: 'Weekday morning peak',
      recurrence: 'Weekdays 07:30–09:00, on 4 of the last 5 weekdays',
      detected_at: '2026-10-08T08:00:00+03:00',
      forecast_outlook: null,
    },
    indicators: ['Queue past the storage bay on 4 of the last 5 weekdays', 'Delay at LOS E in the morning peak'],
    triggered_by: [{ kpi: 'queue_length', level: 'approach', unit: 'm' }],
    recurred: ['2026-09-30', '2026-10-06', '2026-10-08', '2026-10-11', '2026-10-12', '2026-10-14'],
    baseline: [74, 'E', 188, 1.18, 49, 'D'],
    recommendations: [
      {
        title: 'Morning timing plan for the north left turn',
        category: 'signal_timing',
        summary: 'A separate weekday 07:30–09:00 plan with more green for the north left turn.',
        rank_reason: 'Targets the hours when the queue builds up, and leaves other hours unchanged.',
        kpis: [52, 'D', 141, 0.89, 45, 'D'],
      },
      {
        title: 'Lengthen the morning cycle to 140 s',
        category: 'cycle_length',
        summary: 'Adds 20 s to the morning cycle, most of it for the north left turn.',
        rank_reason: 'Also keeps the queue in its bay, but every other approach waits longer.',
        kpis: [58, 'E', 152, 0.95, 48, 'D'],
      },
    ],
  },
}

// The signal cycle with each option. Matches the plans in
// recommendationService.js; every baseline runs a 120 s cycle.
const BASELINE_CYCLE = 120
const FAKE_CYCLES = {
  REC_001_A: 120, REC_001_B: 140, REC_001_C: 120, REC_001_D: 120,
  REC_002_A: 120, REC_002_B: 100,
  REC_003_A: 120, REC_003_B: 140,
  REC_004_A: 120,
  REC_005_A: 120, REC_005_B: 120,
  REC_006_A: 120,
  REC_007_A: 120, REC_007_B: 140,
}

// Turns one FAKE_DATA entry into the shape described at the top.
function build(entry) {
  const id = Number(Object.keys(FAKE_DATA).find((key) => FAKE_DATA[key] === entry))
  const problem = {
    problem_id: id,
    ...INTERSECTION,
    ...entry.problem,
    indicators: entry.indicators,
    triggered_by: entry.triggered_by ?? [],
  }
  if (problem.alert_type === 'pattern') problem.recurrence_days = makeRecurrenceDays(entry.recurred)

  let rank = 0
  const recommendations = entry.recommendations.map((option, i) => {
    const letter = String.fromCharCode(65 + i) // A, B, C...
    const scenarioId = `SCN_INT_00${id}_${letter}`
    const ok = option.kpis !== null
    return {
      recommendation_id: `REC_00${id}_${letter}`,
      rank: ok ? (rank += 1) : null,
      title: option.title,
      category: option.category,
      summary: option.summary,
      rank_reason: option.rank_reason,
      cycle_length_s: FAKE_CYCLES[`REC_00${id}_${letter}`] ?? null,
      scenario_id: scenarioId,
      status: ok ? 'ok' : 'unavailable',
      reason: ok ? null : DID_NOT_FINISH,
      kpis: toKpis(option.kpis, problem, scenarioId),
    }
  })

  const baselineKpis = toKpis(entry.baseline, problem, `SCN_BASE_00${id}`)
  recommendations.forEach((option) => {
    option.comparisons = compareAll(baselineKpis, option.kpis)
  })
  problem.history = makeHistory(problem, baselineKpis)

  return {
    problem,
    baseline: {
      scenario_id: `SCN_BASE_00${id}`,
      cycle_length_s: BASELINE_CYCLE,
      kpis: baselineKpis,
    },
    recommendations,
    isSample: true,
  }
}

// The approaches with an uncontrolled right-turn slip (kpi_engine.md 1.2)
const SLIP_APPROACHES = ['APP_N', 'APP_S', 'APP_W']
const RUNS = 5

// Six numbers → the KpiResult objects listed at the top. The numbers that
// are not in the six are made up from them, for the sample only.
function toKpis(values, problem, scenarioId) {
  const [delay, los, queue, storage, intDelay, intLos] = values ?? []
  const approach = { level: 'approach', approach_id: problem.approach_id }
  const intersection = { level: 'intersection', intersection_id: problem.intersection_id }
  const made = (from, formula) => (from == null ? null : formula(from))
  const round2 = (n) => Math.round(n * 100) / 100

  return [
    sim('control_delay', 's/veh', approach, { value: delay }),
    sim('level_of_service', 'grade', approach, { los_grade: los }),
    sim('queue_length', 'm', approach, { value: queue }),
    sim('queue_length', 'veh', approach, { value: made(queue, (q) => Math.round(q / 7)) }),
    sim('queue_storage_ratio', 'ratio', approach, { value: storage }),
    sim('queue_duration', 's', approach, { value: made(delay, (d) => Math.round(d * 0.75)) }),
    sim('throughput', 'veh/h', approach, { value: made(delay, (d) => Math.round(1800 - d * 6)) }),
    hcm('volume_to_capacity_ratio', 'ratio', approach, { value: made(storage, (r) => round2(0.35 + r * 0.65)) }),
    sim('control_delay', 's/veh', intersection, { value: intDelay }),
    sim('level_of_service', 'grade', intersection, { los_grade: intLos }),
    sim('throughput', 'veh/h', intersection, { value: made(intDelay, (d) => Math.round(5200 - d * 20)) }),
    hcm('volume_to_capacity_ratio', 'ratio', intersection, { value: made(intDelay, (d) => round2(0.5 + d / 160)) }),
  ]

  // A simulation result: the mean of the runs, with their spread
  function sim(kpi, unit, where, measured) {
    const r = result(kpi, 'simulation', unit, where, measured)
    r.run_ids = Array.from({ length: RUNS }, (_, n) => `${scenarioId}_RUN_${n + 1}`)
    r.standard_deviation =
      r.status === 'ok' && r.value != null ? round2(r.value * 0.05) : null
    const hasSlip = where.level === 'intersection' || SLIP_APPROACHES.includes(where.approach_id)
    r.uncontrolled_movements = hasSlip ? 'included' : null
    return r
  }

  // An HCM result: calculated, so no runs and no spread
  function hcm(kpi, unit, where, measured) {
    const r = result(kpi, 'hcm', unit, where, measured)
    r.run_ids = []
    r.standard_deviation = null
    return r
  }

  function result(kpi, method, unit, where, measured) {
    const ok = values != null
    return {
      kpi,
      method,
      unit,
      ...where,
      interval_start: problem.interval_start,
      interval_end: problem.interval_end,
      value: ok ? measured.value ?? null : null,
      los_grade: ok ? measured.los_grade ?? null : null,
      status: ok ? 'ok' : 'unavailable',
      reason: ok ? null : 'The intervention simulation did not finish.',
      scenario_id: scenarioId,
    }
  }
}

// One KpiComparison per KPI of an option against the baseline. The real
// engine uses matched runs; the sample takes the difference of the two
// values and makes up a spread.
function compareAll(baselineKpis, optionKpis) {
  const pairs = Array.from({ length: RUNS }, (_, n) => `PAIR_${n + 1}`)
  return optionKpis.map((after) => {
    const before = baselineKpis.find(
      (r) => r.kpi === after.kpi && r.level === after.level && r.unit === after.unit,
    )
    const isSim = after.method === 'simulation'
    const base = {
      kpi: after.kpi,
      method: after.method,
      unit: after.unit,
      level: after.level,
      approach_id: after.approach_id,
      intersection_id: after.intersection_id,
      interval_start: after.interval_start,
      interval_end: after.interval_end,
      pair_count: isSim ? RUNS : null,
    }
    if (after.status !== 'ok' || before.status !== 'ok') {
      return {
        ...base,
        status: 'unavailable',
        reason: isSim ? `unavailable in ${RUNS} of ${RUNS} pairs` : 'The intervention has no HCM result.',
        used_pairs: [],
        is_partial_sample: false,
      }
    }
    if (after.kpi === 'level_of_service') {
      return {
        ...base,
        status: 'ok',
        reason: null,
        baseline_grade: before.los_grade,
        intervention_grade: after.los_grade,
        used_pairs: pairs,
        is_partial_sample: false,
      }
    }
    const change = Math.round((after.value - before.value) * 100) / 100
    return {
      ...base,
      status: 'ok',
      reason: null,
      baseline_mean: before.value,
      change,
      change_standard_deviation: isSim ? Math.round(Math.abs(change) * 0.12 * 100) / 100 : null,
      percent_change: before.value ? Math.round((change / before.value) * 1000) / 10 : null,
      used_pairs: isSim ? pairs : [],
      is_partial_sample: false, // the sample uses every pair
    }
  })
}

// The engine's reason when an interval has no delay (kpi_engine.md 7.4)
const MISSING_REASON =
  '2 vehicles had not finished their passage when the run ended; increase the clearance duration.'

// The HCM grade for a delay (kpi_engine.md 3.2). The real engine sends the
// grade; the sample works it out so it matches the delay.
function sampleGrade(delay) {
  const limits = [10, 20, 35, 55, 80]
  const index = limits.findIndex((limit) => delay <= limit)
  return 'ABCDEF'[index === -1 ? 5 : index]
}

// The past two hours of control delay, per 15-minute interval, then the forecast
// at 15, 30, 45 and 60 minutes (none for a pattern alert). For a forecast
// alert the analysis window itself is forecast. One past interval is
// missing on purpose, to show the gap.
function makeHistory(problem, baselineKpis) {
  const kpi = 'control_delay'
  const peakResult = baselineKpis.find((r) => r.kpi === kpi && r.level === 'approach')
  const peak = peakResult.value
  const firstForecast = problem.alert_type === 'forecast' ? 0 : 1
  const lastIndex = problem.alert_type === 'pattern' ? 0 : firstForecast + 3

  const points = []
  for (let i = -7; i <= lastIndex; i++) {
    const kind = i >= firstForecast ? 'forecast' : 'past'
    const share = i <= 0 ? 0.45 + 0.55 * ((i + 7) / 7) ** 1.5 : 1 - 0.06 * i + 0.01 * Math.sin(i)
    const missing = i === -4
    const value = missing ? null : Math.round(peak * share)
    points.push({
      interval_start: addMinutes(problem.interval_start, i * 15),
      interval_end: addMinutes(problem.interval_start, (i + 1) * 15),
      kind,
      value,
      los_grade: missing ? null : sampleGrade(value),
      status: missing ? 'unavailable' : 'ok',
      reason: missing ? MISSING_REASON : null,
    })
  }

  return { kpi, method: peakResult.method, unit: peakResult.unit, points }
}

// A recurring alert's recent weekdays: three weeks, Sunday to Thursday, up
// to the day of the sample, with the days it recurred (by default 7, 11, 13
// and 14 Oct: "3 of the last 5 weekdays"). One day has no data, to show the gap.
function makeRecurrenceDays(recurred = ['2026-10-07', '2026-10-11', '2026-10-13', '2026-10-14']) {
  const dates = [
    '2026-09-27', '2026-09-28', '2026-09-29', '2026-09-30', '2026-10-01',
    '2026-10-04', '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08',
    '2026-10-11', '2026-10-12', '2026-10-13', '2026-10-14',
  ]
  return dates.map((date, i) => {
    const missing = date === '2026-10-05'
    const occurred = recurred.includes(date)
    const value = missing ? null : occurred ? 62 + (i % 3) * 3 : 38 + (i % 4) * 4
    return {
      date,
      occurred: missing ? null : occurred,
      value,
      los_grade: missing ? null : sampleGrade(value),
      status: missing ? 'unavailable' : 'ok',
      reason: missing ? 'No simulation run for this day.' : null,
    }
  })
}

// "2026-10-14T07:45:00+03:00" plus 15 minutes → "2026-10-14T08:00:00+03:00"
function addMinutes(timestamp, minutes) {
  const [h, m] = timestamp.slice(11, 16).split(':').map(Number)
  const total = h * 60 + m + minutes
  const pad = (n) => String(n).padStart(2, '0')
  return `${timestamp.slice(0, 11)}${pad(Math.floor(total / 60))}:${pad(total % 60)}${timestamp.slice(16)}`
}
