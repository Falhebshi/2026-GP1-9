// Where the Recommendation Details page gets its data.
//
// FAKE for now. When the backend is ready, only the inside of
// getRecommendation() changes; the page stays the same as long as the data
// keeps this shape.
//
// PROPOSED CONTRACT (agree it with the backend team):
//
//   getRecommendation(problemId, recommendationId)
//
//   {
//     problem: { ...same as in alertDetailsService },
//
//     recommendation: {
//       recommendation_id, rank,                 rank 1 = best; null when the
//                                                option could not be ranked
//       title, category, summary, rank_reason,
//       status: 'ok' | 'unavailable', reason,
//       signal_plan: {                           null when not known
//         before: { cycle_length_s, phases: [{ phase_id, name, green_s }] },
//         after:  { cycle_length_s, phases: [{ phase_id, name, green_s }] },
//       },                                       the page shows the rest of
//                                                each cycle as amber and
//                                                all-red; if the backend can
//                                                send yellow_s and all_red_s
//                                                per phase, it can show them
//     },
//
//     options: [                                 every option for the same
//       { recommendation_id, rank, title },      problem, in rank order, to
//     ],                                         switch between them
//
//     comparison: {                              PBI 30
//       interval_start, interval_end,            the same period for both
//       duration_s,                              length of the playback
//       replications,                            matched runs per scenario
//       baseline:     { scenario_id, status, reason, run_ids, kpis },
//       intervention: { scenario_id, status, reason, run_ids, kpis },
//       changes: [KpiComparison, ...],           one per KPI, from the
//     },                                         engine's matched runs
//
//     isSample: true,                            true only while this is fake
//   }
//
//   Every kpis list holds the KpiResult objects listed in
//   alertDetailsService.js: simulation results are the mean of the
//   matched runs with standard_deviation; HCM results (v/c) have neither.
//   changes holds KpiComparison objects (also described there): the
//   engine's paired change for each KPI, with its spread, the grades for
//   level of service, and is_partial_sample when pairs were left out.
//
//   The frontend never calculates a KPI or a change: it shows the
//   backend's values side by side, formatted by utils/kpi.js.

import { getAlertDetails } from './alertDetailsService'

export async function getRecommendation(problemId, recommendationId) {
  // Later: return (await fetch(`/api/recommendations/${recommendationId}`)).json()
  // The fake version starts from the Alert Details sample data, so both
  // pages show the same numbers. getAlertDetails() also handles the
  // ?demo=error test and the 300 ms wait.
  const data = await getAlertDetails(problemId)

  const recommendation = data.recommendations.find(
    (option) => option.recommendation_id === recommendationId,
  )
  if (!recommendation) {
    throw new Error('This intervention could not be found. It may no longer be recommended.')
  }

  const ok = recommendation.status === 'ok'

  return {
    problem: data.problem,
    recommendation: {
      ...recommendation,
      signal_plan: FAKE_SIGNAL_PLANS[recommendation.recommendation_id] ?? null,
    },
    options: [...data.recommendations]
      .sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
      .map(({ recommendation_id, rank, title }) => ({ recommendation_id, rank, title })),
    comparison: {
      interval_start: data.problem.interval_start,
      interval_end: data.problem.interval_end,
      duration_s: 900, // 15 minutes
      replications: 5,
      baseline: {
        scenario_id: data.baseline.scenario_id,
        status: 'ok',
        reason: null,
        run_ids: runIds(data.baseline.scenario_id),
        kpis: data.baseline.kpis,
      },
      intervention: {
        scenario_id: recommendation.scenario_id,
        status: recommendation.status,
        reason: ok ? null : 'The intervention simulation did not finish.',
        run_ids: ok ? runIds(recommendation.scenario_id) : [],
        kpis: recommendation.kpis,
      },
      changes: recommendation.comparisons,
    },
    isSample: true,
  }
}

// ---- Fake data ------------------------------------------------------------
// Everything below this line is deleted when the backend is connected.

// Signal timing for every option. Each problem has the base plan of its
// period, with the problem approach's phase first (the animation reads it).
// Green times plus 12 s of amber and all-red make up each cycle.
const PHASES = {
  N_LEFT: { phase_id: 'P1', name: 'North left turn' },
  EW: { phase_id: 'P2', name: 'East–west through' },
  E_LEFT: { phase_id: 'P3', name: 'East left turn' },
  S: { phase_id: 'P4', name: 'South' },
  E: { phase_id: 'P6', name: 'East through' },
  W: { phase_id: 'P7', name: 'West through' },
  N: { phase_id: 'P8', name: 'North' },
}

// [phase, green_s] in cycle order, then the cycle length
function plan(cycle, greens) {
  return {
    cycle_length_s: cycle,
    phases: greens.map(([phase, green_s]) => ({ ...phase, green_s })),
  }
}

const { N_LEFT, EW, E_LEFT, S, E, W, N } = PHASES

// Morning peak (problems 1 and 7): the north left turn first
const MORNING = plan(120, [[N_LEFT, 24], [EW, 48], [E_LEFT, 14], [S, 22]])
// East and west through phases split (problems 2, 3 and 5)
const SPLIT_EAST = plan(120, [[E, 34], [W, 34], [N, 20], [S, 20]])
const SPLIT_WEST = plan(120, [[W, 34], [E, 34], [N, 20], [S, 20]])
// South approach first (problems 4 and 6)
const SOUTH = plan(120, [[S, 22], [N_LEFT, 24], [EW, 48], [E_LEFT, 14]])
const SOUTH_LONG = plan(120, [[S, 30], [N_LEFT, 24], [EW, 40], [E_LEFT, 14]])

const FAKE_SIGNAL_PLANS = {
  // 1 Queue spillback, north approach
  REC_001_A: { before: MORNING, after: plan(120, [[N_LEFT, 36], [EW, 36], [E_LEFT, 14], [S, 22]]) },
  REC_001_B: { before: MORNING, after: plan(140, [[N_LEFT, 38], [EW, 52], [E_LEFT, 15], [S, 23]]) },
  REC_001_C: {
    before: MORNING,
    after: plan(120, [
      [{ ...N_LEFT, name: 'North left turn (leading)' }, 18],
      [EW, 41],
      [{ phase_id: 'P5', name: 'North left turn (lagging)' }, 10],
      [E_LEFT, 14],
      [S, 22],
    ]),
  },
  REC_001_D: { before: MORNING, after: plan(120, [[N_LEFT, 30], [EW, 48], [E_LEFT, 8], [S, 22]]) },
  // 2 Low average speed, east approach
  REC_002_A: { before: SPLIT_EAST, after: plan(120, [[E, 40], [W, 28], [N, 20], [S, 20]]) },
  REC_002_B: { before: SPLIT_EAST, after: plan(100, [[E, 28], [W, 28], [N, 16], [S, 16]]) },
  // 3 High V/C ratio, west approach (forecast)
  REC_003_A: { before: SPLIT_WEST, after: plan(120, [[W, 42], [E, 30], [N, 18], [S, 18]]) },
  REC_003_B: { before: SPLIT_WEST, after: plan(140, [[W, 40], [E, 40], [N, 24], [S, 24]]) },
  // 4 Queue buildup, south approach (forecast)
  REC_004_A: { before: SOUTH, after: plan(120, [[S, 30], [N_LEFT, 24], [EW, 40], [E_LEFT, 14]]) },
  // 5 Recurring low speed, east approach
  REC_005_A: { before: SPLIT_EAST, after: plan(120, [[E, 44], [W, 28], [N, 18], [S, 18]]) },
  REC_005_B: { before: SPLIT_EAST, after: plan(120, [[E, 38], [W, 30], [N, 20], [S, 20]]) },
  // 6 Signal timing issue, south approach: the south green is longer than needed
  REC_006_A: { before: SOUTH_LONG, after: SOUTH },
  // 7 Recurring queue buildup, north approach (weekday mornings)
  REC_007_A: { before: MORNING, after: plan(120, [[N_LEFT, 34], [EW, 38], [E_LEFT, 14], [S, 22]]) },
  REC_007_B: { before: MORNING, after: plan(140, [[N_LEFT, 36], [EW, 54], [E_LEFT, 15], [S, 23]]) },
}

function runIds(scenarioId) {
  return [1, 2, 3, 4, 5].map((n) => `${scenarioId}_RUN_${n}`)
}
