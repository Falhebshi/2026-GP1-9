import { useEffect, useRef, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import Breadcrumbs from '../components/Breadcrumbs'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import InfoList from '../components/InfoList'
import KpiTile from '../components/KpiTile'
import LosBadge from '../components/LosBadge'
import Notice from '../components/Notice'
import MethodTag from '../components/MethodTag'
import PageHeader from '../components/PageHeader'
import PlaybackBar from '../components/PlaybackBar'
import SimulationViewport from '../components/SimulationViewport'
import usePlayback from '../hooks/usePlayback'
import { getRecommendation } from '../services/recommendationService'
import { timeRange } from '../utils/format'
import {
  KPI_DEFINITIONS,
  STATUS_LABELS,
  comparisonProps,
  displayUnit,
  formatChangeAmount,
  formatKpiValue,
  hasValue,
  isOverLimit,
  kpiTileProps,
  partialSampleNote,
} from '../utils/kpi'
import './RecommendationDetails.css'

// Recommendation Details page,
// "/alerts/:problemId/recommendations/:recommendationId" (PBI 29 and 30).
// Opened from an option on the Alert Details page. It shows the
// intervention and its expected KPIs (PBI 29), and on request the baseline
// and intervention simulations side by side with every KPI (PBI 30).
//
// All values come from recommendationService.js; the page never calculates a
// KPI. Try ?demo=error for the error state.

// The kinds of signal-timing change
const CATEGORY_LABELS = {
  signal_timing: 'Green split change',
  cycle_length: 'Cycle length change',
  phase_sequence: 'Phase sequence change',
}

// Expected performance tiles, grouped like the baseline on Alert Details
const APPROACH_KPIS = [
  { kpi: 'queue_storage_ratio', level: 'approach', label: 'Storage ratio' },
  { kpi: 'queue_length', level: 'approach', unit: 'm', label: 'Longest queue' },
  { kpi: 'control_delay', level: 'approach', label: 'Control delay', los: true },
]
const INTERSECTION_KPIS = [
  { kpi: 'control_delay', level: 'intersection', label: 'Control delay', los: true },
]

// Rows of the before-and-after table, in the same order as on
// Alert Details. unit tells apart the two queue lengths (m and veh).
const COMPARISON_GROUPS = [
  {
    level: 'approach',
    rows: [
      { kpi: 'control_delay' },
      { kpi: 'level_of_service' },
      { kpi: 'queue_length', unit: 'm', label: 'Longest queue' },
      { kpi: 'queue_length', unit: 'veh', label: 'Longest queue' },
      { kpi: 'queue_storage_ratio' },
      { kpi: 'queue_duration', hint: 'Average time stopped per vehicle' },
      { kpi: 'volume_to_capacity_ratio', label: 'Highest v/c' },
      { kpi: 'throughput' },
    ],
  },
  {
    level: 'intersection',
    title: 'Whole intersection',
    rows: [
      { kpi: 'control_delay' },
      { kpi: 'level_of_service' },
      { kpi: 'volume_to_capacity_ratio', label: 'Critical v/c' },
      { kpi: 'throughput' },
    ],
  },
]

function RecommendationDetails() {
  const { problemId, recommendationId } = useParams()

  // The last result, with the option it is for. A result for another
  // option counts as still loading, so nothing has to be cleared.
  const key = `${problemId}/${recommendationId}`
  const [loaded, setLoaded] = useState({ key: null, data: null, error: null })
  const data = loaded.key === key ? loaded.data : null
  const error = loaded.key === key ? loaded.error : null
  // ?view=compare in the address opens the comparison directly
  const [searchParams, setSearchParams] = useSearchParams()
  const [comparing, setComparing] = useState(searchParams.get('view') === 'compare')
  const comparisonRef = useRef(null)
  const expectedRef = useRef(null)

  // Closing also clears ?view=compare and scrolls back to the button
  function closeComparison() {
    setComparing(false)
    if (searchParams.has('view')) {
      const next = new URLSearchParams(searchParams)
      next.delete('view')
      setSearchParams(next, { replace: true })
    }
    expectedRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  useEffect(() => {
    let cancelled = false // true if the user leaves before the data arrives

    getRecommendation(problemId, recommendationId)
      .then((result) => {
        if (!cancelled) setLoaded({ key: `${problemId}/${recommendationId}`, data: result, error: null })
      })
      .catch((err) => {
        if (!cancelled) setLoaded({ key: `${problemId}/${recommendationId}`, data: null, error: err.message })
      })

    return () => {
      cancelled = true
    }
  }, [problemId, recommendationId])

  useEffect(() => {
    if (comparing) comparisonRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [comparing])

  const backTo = `/alerts/${problemId}`
  const problem = data?.problem
  const option = data?.recommendation

  const header = (
    <>
      <Breadcrumbs
        items={[
          { label: 'Alerts', to: '/alerts' },
          { label: problem?.title ?? 'Alert details', to: backTo },
          { label: option?.title ?? 'Recommendation details' },
        ]}
      />
      <PageHeader title={option?.title ?? 'Recommendation details'} />
    </>
  )

  if (error) {
    return (
      <>
        {header}
        <EmptyState variant="error" title="Recommendation details unavailable">
          {error}
        </EmptyState>
      </>
    )
  }

  if (!data) {
    return (
      <>
        {header}
        <EmptyState>Loading the recommendation…</EmptyState>
      </>
    )
  }

  const { comparison } = data
  const optionKpis = comparison.intervention.kpis
  const available = option.status === 'ok'

  return (
    <>
      {header}

      {data.options.length > 1 && (
        <OptionSwitcher options={data.options} current={option.recommendation_id} problemId={problemId} />
      )}

      {data.isSample && (
        <Notice variant="warning" className="recommendation-notice">
          Sample data for layout only. These are not real simulation results.
        </Notice>
      )}

      {/* ---- PBI 29: the details ---- */}
      <section className="recommendation-about" aria-labelledby="recommendation-about-title">
        <h2 id="recommendation-about-title" className="recommendation-section-title">
          The intervention
        </h2>
        <InterventionRecord option={option} problem={problem} available={available} />
      </section>

      <section
        ref={expectedRef}
        className="recommendation-section"
        aria-labelledby="recommendation-expected-title"
      >
        <h2 id="recommendation-expected-title" className="recommendation-section-title recommendation-section-heading">
          Expected performance
        </h2>

        <div className={`recommendation-groups recommendation-groups-${problem.alert_type}`}>
          <TileGroup
            title={problem.location}
            items={APPROACH_KPIS}
            kpis={optionKpis}
            changes={comparison.changes}
            problem={problem}
          />
          <TileGroup
            title="Whole intersection"
            items={INTERSECTION_KPIS}
            kpis={optionKpis}
            changes={comparison.changes}
            problem={problem}
          />
        </div>

        {!comparing && (
          <Button variant="secondary" className="recommendation-compare-open" onClick={() => setComparing(true)}>
            Compare before and after
          </Button>
        )}
      </section>

      {/* ---- PBI 30: the before-and-after comparison ---- */}
      {comparing && (
        <section
          ref={comparisonRef}
          className="recommendation-section recommendation-comparison"
          aria-labelledby="recommendation-compare-title"
        >
          <div className="recommendation-section-header">
            <h2 id="recommendation-compare-title" className="recommendation-section-title">
              Before and after
            </h2>
            <Button variant="secondary" size="sm" onClick={closeComparison}>
              Close comparison
            </Button>
          </div>
          <p className="recommendation-section-text">
            Both simulations cover {timeRange(comparison.interval_start, comparison.interval_end)}{' '}
            with the same traffic demand.
          </p>

          {comparison.intervention.status !== 'ok' && (
            <Notice variant="warning" className="recommendation-notice">
              The impact of this intervention cannot be evaluated.{' '}
              {comparison.intervention.reason ?? ''}
            </Notice>
          )}

          <Comparison data={data} />
        </section>
      )}
    </>
  )
}

// The intervention's facts in a tinted sidebar, with what it does, why,
// and its signal timing beside them
function InterventionRecord({ option, problem, available }) {
  const cycle = option.signal_plan
    ? option.signal_plan.before.cycle_length_s === option.signal_plan.after.cycle_length_s
      ? `${option.signal_plan.after.cycle_length_s} s`
      : `${option.signal_plan.before.cycle_length_s} s to ${option.signal_plan.after.cycle_length_s} s`
    : undefined

  return (
    <div className="recommendation-record">
      <div className={`recommendation-record-side recommendation-record-side-${problem.alert_type}`}>
        <InfoList
          className="recommendation-record-facts"
          items={[
            { label: 'Location', value: problem.location },
            { label: 'Type', value: CATEGORY_LABELS[option.category] },
            {
              label: 'Period',
              value: problem.interval_start ? timeRange(problem.interval_start, problem.interval_end) : undefined,
            },
            { label: 'Cycle length', value: cycle },
          ]}
        />
      </div>

      <div className="recommendation-record-main">
        <div className="recommendation-record-text">
          <h3 className="recommendation-record-heading">What it does</h3>
          <p className="recommendation-record-description">{option.summary}</p>

          {available ? (
            <>
              <h3 className="recommendation-record-heading">Why Jaadah recommends this option</h3>
              <p>{option.rank_reason ?? <Unavailable />}</p>
            </>
          ) : (
            <p className="recommendation-unavailable" role="note">
              {option.reason ?? 'The expected impact of this intervention is unavailable.'}
            </p>
          )}
        </div>

        <div className="recommendation-record-timing">
          <h3 className="recommendation-record-heading">Signal timing changes</h3>
          <SignalPlan plan={option.signal_plan} />
        </div>
      </div>
    </div>
  )
}

// One group of expected-performance tiles, each with its change vs baseline
function TileGroup({ title, items, kpis, changes, problem }) {
  return (
    <div className="recommendation-group">
      <h3 className="recommendation-group-title">{title}</h3>
      <div className="recommendation-group-tiles">
        {items.map((item) => {
          const result = findKpi(kpis, item, problem)
          const tile = kpiTileProps(result)
          return (
            <KpiTile
              key={`${item.level}-${item.kpi}-${item.unit ?? ''}`}
              layout="stacked"
              label={item.label}
              {...tile}
              tag={result?.method === 'simulation' ? undefined : tile.tag}
              {...comparisonProps(findKpi(changes, item, problem), 'vs baseline')}
              detail={detailFor(item, kpis, problem)}
            />
          )
        })}
      </div>
    </div>
  )
}

// Links to the other options for this problem
function OptionSwitcher({ options, current, problemId }) {
  return (
    <nav className="recommendation-options" aria-label="Options for this problem">
      <h2 className="recommendation-options-label">Options for this problem</h2>
      <ul className="recommendation-options-list">
        {options.map((item) => {
          const isCurrent = item.recommendation_id === current
          return (
            <li key={item.recommendation_id}>
              <Link
                to={`/alerts/${problemId}/recommendations/${item.recommendation_id}`}
                className={`recommendation-option ${isCurrent ? 'recommendation-option-current' : ''}`}
                aria-current={isCurrent ? 'page' : undefined}
              >
                <span className="recommendation-option-rank" aria-label={item.rank ? `Rank ${item.rank}` : 'Not ranked'}>
                  {item.rank ?? '–'}
                </span>
                {item.title}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

// Both simulations on one playback bar, then the KPI table
function Comparison({ data }) {
  const { problem, recommendation: option, comparison } = data
  const playback = usePlayback({ duration: comparison.duration_s })
  const clock = clockAt(comparison.interval_start, playback.time)

  const plan = option.signal_plan
  const baselineCanPlay = comparison.baseline.status === 'ok'

  return (
    <>
      <div className="recommendation-viewports">
        <SimulationViewport
          title="Baseline"
          height={300}
          timeLabel={clock}
          error={baselineCanPlay ? undefined : comparison.baseline.reason}
        >
          <IntersectionSketch
            time={playback.time}
            approachId={problem.approach_id}
            storageRatio={findKpi(comparison.baseline.kpis, { kpi: 'queue_storage_ratio', level: 'approach' }, problem)}
            plan={plan?.before}
          />
        </SimulationViewport>

        <SimulationViewport
          title="With intervention"
          height={300}
          timeLabel={clock}
          error={comparison.intervention.status === 'ok' ? undefined : comparison.intervention.reason}
        >
          <IntersectionSketch
            time={playback.time}
            approachId={problem.approach_id}
            storageRatio={findKpi(comparison.intervention.kpis, { kpi: 'queue_storage_ratio', level: 'approach' }, problem)}
            plan={plan?.after}
          />
        </SimulationViewport>
      </div>

      <Card className="recommendation-playback">
        <PlaybackBar
          duration={comparison.duration_s}
          time={playback.time}
          onTimeChange={playback.setTime}
          playing={playback.playing}
          onPlayingChange={playback.setPlaying}
          speed={playback.speed}
          onSpeedChange={playback.setSpeed}
          disabled={!baselineCanPlay}
        />
      </Card>

      <ComparisonTable data={data} />
    </>
  )
}

// Every KPI for the baseline and the intervention. The change comes from
// the engine's comparison of matched runs, never from subtracting values.
function ComparisonTable({ data }) {
  const { problem, recommendation: option, comparison } = data
  const plan = option.signal_plan
  const cycle = (seconds) => (seconds != null ? `${seconds} s cycle` : 'Cycle unavailable')

  return (
    <>
      <Card className="recommendation-table-box">
        <div
          className="recommendation-table-wrap"
          tabIndex={0}
          role="region"
          aria-labelledby="recommendation-compare-title"
        >
          <table className="recommendation-table">
            <thead>
              <tr>
                <th scope="col">
                  <span className="recommendation-visually-hidden">KPI</span>
                </th>
                <th scope="col" className="recommendation-col-base">
                  <span className="recommendation-col-head">
                    <span className="recommendation-rank recommendation-rank-base" aria-hidden="true">B</span>
                    <span>
                      <span className="recommendation-col-name">Baseline</span>
                      <span className="recommendation-col-meta">{cycle(plan?.before.cycle_length_s)}</span>
                    </span>
                  </span>
                </th>
                <th scope="col">
                  <span className="recommendation-col-head">
                    <span
                      className={`recommendation-rank ${option.rank === 1 ? 'recommendation-rank-top' : ''}`}
                      aria-label={option.rank ? `Rank ${option.rank}` : 'Not ranked'}
                    >
                      {option.rank ?? '–'}
                    </span>
                    <span>
                      <span className="recommendation-col-name">With intervention</span>
                      <span className="recommendation-col-meta">{cycle(plan?.after.cycle_length_s)}</span>
                    </span>
                  </span>
                </th>
              </tr>
            </thead>

            {COMPARISON_GROUPS.map((group) => (
              <tbody key={group.level}>
                <tr className="recommendation-table-group">
                  <th scope="colgroup" colSpan={3}>
                    {group.title ?? problem.location}
                  </th>
                </tr>
                {group.rows.map((row) => {
                  const where = { ...row, level: group.level }
                  const before = findKpi(comparison.baseline.kpis, where, problem)
                  const after = findKpi(comparison.intervention.kpis, where, problem)
                  const unit = displayUnit((before ?? after)?.unit)
                  return (
                    <tr key={`${row.kpi}-${row.unit ?? ''}`}>
                      <th scope="row">
                        <span className="recommendation-row-label">
                          {row.label ?? KPI_DEFINITIONS[row.kpi].label}
                          {unit && <span className="recommendation-unit"> ({unit})</span>}
                          {before?.method === 'hcm' && <MethodTag method="hcm" />}
                        </span>
                        {row.hint && <span className="recommendation-row-hint">{row.hint}</span>}
                      </th>
                      <td className="recommendation-col-base">
                        <KpiValue result={before} />
                      </td>
                      <td>
                        <KpiValue result={after} />
                        <KpiChange comparison={findKpi(comparison.changes, where, problem)} />
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            ))}
          </table>
        </div>
      </Card>
      <p className="recommendation-table-note">
        ± is the spread across the {comparison.replications} runs of each scenario (for a change, across the{' '}
        {comparison.replications} matched pairs).
      </p>
    </>
  )
}

// A value with its spread across runs, red when over its limit
function KpiValue({ result }) {
  if (!hasValue(result)) {
    return (
      <span className="recommendation-muted" title={result?.reason ?? undefined}>
        {formatKpiValue(result)}
      </span>
    )
  }
  if (result.kpi === 'level_of_service') return <LosBadge grade={result.los_grade} />

  const over = isOverLimit(result)
  const spread = result.standard_deviation

  return (
    <span className="recommendation-value-line">
      <span className={`recommendation-value ${over ? 'recommendation-value-over' : ''}`}>{formatKpiValue(result)}</span>
      {spread != null && (
        <span className="recommendation-spread">
          {' '}± {spread.toLocaleString('en-US', { maximumFractionDigits: Math.max(1, KPI_DEFINITIONS[result.kpi]?.decimals ?? 0) })}
        </span>
      )}
    </span>
  )
}

// The engine's change (direction, size and amount ± spread). LOS has no
// amount: the two badges already show the move.
function KpiChange({ comparison }) {
  if (!comparison || comparison.status !== 'ok' || comparison.kpi === 'level_of_service') return null

  const partial = partialSampleNote(comparison)
  const { change, changeUnit, changeTone, changeNote } = comparisonProps(comparison)
  if (change === undefined) return null

  const arrow = change > 0 ? '↑' : change < 0 ? '↓' : ''
  const amount = formatChangeAmount(comparison)
  return (
    <>
      <span className={`recommendation-change recommendation-change-${changeTone}`}>
        {arrow} {changeText(change, changeUnit, comparison.kpi)}
        {changeUnit} {changeNote}
      </span>
      {changeUnit === '%' && amount && <span className="recommendation-change-amount">{amount}</span>}
      {changeUnit !== '%' && comparison.change_standard_deviation != null && (
        <span className="recommendation-change-amount">
          ± {comparison.change_standard_deviation.toLocaleString('en-US', { maximumFractionDigits: 2 })}
        </span>
      )}
      {partial && <span className="recommendation-partial">{partial}</span>}
    </>
  )
}

// Signal timing before and after as two bars: each phase's green time is
// sized by its share of the cycle, and the striped end is amber and all-red.
// The values are also in a table for screen readers.
const PHASE_COLORS = 5 // recommendation-phase-1 … -5 in RecommendationDetails.css

function SignalPlan({ plan }) {
  if (!plan) {
    return (
      <EmptyState title="Signal timing unavailable">
        The timing plan for this intervention has not been provided.
      </EmptyState>
    )
  }

  // Phases keep the same color in both bars
  const ids = [
    ...plan.after.phases.map((phase) => phase.phase_id),
    ...plan.before.phases.map((phase) => phase.phase_id),
  ].filter((id, i, all) => all.indexOf(id) === i)
  const colorOf = (id) => (ids.indexOf(id) % PHASE_COLORS) + 1
  const phaseIn = (which, id) => plan[which].phases.find((p) => p.phase_id === id)

  const longest = Math.max(plan.before.cycle_length_s, plan.after.cycle_length_s)
  const ticks = Array.from({ length: Math.floor(longest / 30) + 1 }, (_, i) => i * 30)
  // The plan only lists greens, so amber and all-red is the rest of the cycle
  const clearance = (cycle) => cycle.cycle_length_s - cycle.phases.reduce((sum, p) => sum + p.green_s, 0)

  const rows = [
    ...ids.map((id) => ({
      key: id,
      name: (phaseIn('after', id) ?? phaseIn('before', id)).name,
      color: `recommendation-phase-${colorOf(id)}`,
      before: phaseIn('before', id)?.green_s,
      after: phaseIn('after', id)?.green_s,
    })),
    {
      key: 'clearance',
      name: 'Amber and all-red',
      color: 'recommendation-timing-lost',
      before: clearance(plan.before),
      after: clearance(plan.after),
    },
    {
      key: 'cycle',
      name: 'Cycle length',
      before: plan.before.cycle_length_s,
      after: plan.after.cycle_length_s,
    },
  ]

  return (
    <>
      <div className="recommendation-timing" aria-hidden="true">
        {[
          { label: 'Before', cycle: plan.before },
          { label: 'After', cycle: plan.after },
        ].map(({ label, cycle }) => (
          <div key={label} className="recommendation-timing-row">
            <span className="recommendation-timing-label">{label}</span>
            {/* Inline styles only pass numbers into CSS */}
            <div className="recommendation-timing-bar" style={{ '--length': cycle.cycle_length_s / longest }}>
              {cycle.phases.map((phase) => (
                <span
                  key={phase.phase_id}
                  className={`recommendation-timing-phase recommendation-phase-${colorOf(phase.phase_id)}`}
                  style={{ '--share': phase.green_s / cycle.cycle_length_s }}
                >
                  {phase.green_s}
                </span>
              ))}
              <span
                className="recommendation-timing-phase recommendation-timing-lost"
                style={{ '--share': clearance(cycle) / cycle.cycle_length_s }}
              >
                {clearance(cycle)}
              </span>
            </div>
            <span className="recommendation-timing-cycle">{cycle.cycle_length_s} s</span>
          </div>
        ))}

        {/* Seconds into the cycle, every 30 s */}
        <div className="recommendation-timing-row">
          <span />
          <div className="recommendation-timing-axis">
            {ticks.map((tick, i) => (
              <span key={tick} className={i % 2 ? 'recommendation-timing-tick-odd' : ''} style={{ '--at': tick / longest }}>
                {tick} s
              </span>
            ))}
          </div>
          <span />
        </div>
      </div>

      {/* Color key */}
      <ul className="recommendation-timing-key" aria-hidden="true">
        {rows
          .filter((row) => row.color)
          .map((row) => (
            <li key={row.key}>
              <span className={`recommendation-timing-swatch ${row.color}`} />
              {row.name}
            </li>
          ))}
      </ul>

      {/* The same values as text, for screen readers */}
      <table className="recommendation-visually-hidden">
        <caption>Signal timing before and after, in seconds</caption>
        <thead>
          <tr>
            <th scope="col">Phase</th>
            <th scope="col">Before</th>
            <th scope="col">After</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <th scope="row">{row.name}</th>
              <td>{row.before != null ? `${row.before} s` : 'New'}</td>
              <td>{row.after != null ? `${row.after} s` : 'Removed'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

// A simple animation of the problem approach, until the simulation view is
// connected. The queue grows on red and clears on green; its longest length
// is the storage ratio times the bay, so a ratio over 1 spills past it.
const ROTATION = { APP_N: 0, APP_E: 90, APP_S: 180, APP_W: 270 }

// The part of the drawing to show, so the queue fills the viewport
const VIEW = {
  APP_N: '60 0 180 190',
  APP_E: '110 60 190 180',
  APP_S: '60 110 180 190',
  APP_W: '0 60 190 180',
}
const BAY = 90 // length of the turning bay in the drawing
const CAR = 10 // space one car takes in the queue, including the gap

function IntersectionSketch({ time, approachId, storageRatio, plan }) {
  const cycle = plan?.cycle_length_s ?? 120
  const green = plan?.phases?.[0]?.green_s ?? 24
  const ratio = hasValue(storageRatio) ? storageRatio.value : 0

  const inCycle = time % cycle
  const isGreen = inCycle < green
  const shortest = 0.15
  const fill = isGreen
    ? 1 - (inCycle / green) * (1 - shortest)
    : shortest + ((inCycle - green) / (cycle - green)) * (1 - shortest)
  const cars = Math.floor((fill * ratio * BAY) / CAR)

  const distance = time * 9

  return (
    <svg
      viewBox={VIEW[approachId] ?? VIEW.APP_N}
      preserveAspectRatio="xMidYMid meet"
      className="recommendation-sketch"
      role="img"
      aria-label={`Queue ${ratio > 1 ? 'spills past' : 'stays inside'} the turning bay`}
    >
      <g transform={`rotate(${ROTATION[approachId] ?? 0} 150 150)`}>
        {/* Long enough to reach the edges of any viewport */}
        <rect className="recommendation-sketch-road" x="-300" y="130" width="900" height="40" />
        <rect className="recommendation-sketch-road" x="130" y="-300" width="40" height="900" />

        {[0, 1, 2, 3].map((i) => (
          <rect
            key={i}
            className="recommendation-sketch-moving"
            x={((i * 85 + distance) % 340) - 20}
            y="153"
            width="10"
            height="6"
            rx="1.5"
          />
        ))}

        {/* The stop line and the back of the turning bay */}
        <line className="recommendation-sketch-stop" x1="130" y1="128" x2="150" y2="128" />
        <line className="recommendation-sketch-bay" x1="128" y1={128 - BAY} x2="152" y2={128 - BAY} />

        {/* Cars past the bay are the spillback */}
        {Array.from({ length: cars }, (_, i) => {
          const y = 128 - (i + 1) * CAR
          const spilled = y < 128 - BAY
          return (
            <rect
              key={i}
              className={spilled ? 'recommendation-sketch-spilled' : 'recommendation-sketch-car'}
              x="135"
              y={y + 2}
              width="10"
              height={CAR - 3}
              rx="1.5"
            />
          )
        })}

        <circle
          className={isGreen ? 'recommendation-sketch-green' : 'recommendation-sketch-red'}
          cx="122"
          cy="122"
          r="4"
        />
      </g>
    </svg>
  )
}

// ---- Small helpers ----------------------------------------------------------

function Unavailable() {
  return <span className="recommendation-muted">{STATUS_LABELS.unavailable}</span>
}

// A change without its sign, keeping the KPI's decimals (0.10, not 0.1)
function changeText(change, changeUnit, kpi) {
  const decimals = changeUnit === '%' ? 0 : KPI_DEFINITIONS[kpi]?.decimals ?? 0
  return Math.abs(change).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

// Finds a KPI result or comparison at the problem's approach or
// intersection. unit is only needed for queue length (m or veh).
function findKpi(kpis, { kpi, level, unit }, problem) {
  return kpis?.find(
    (result) =>
      result.kpi === kpi &&
      result.level === level &&
      (!unit || result.unit === unit) &&
      (level === 'approach'
        ? result.approach_id === problem.approach_id
        : result.intersection_id === problem.intersection_id),
  )
}

// The grey line under a tile: LOS under delay, vehicles under queue
function detailFor(item, kpis, problem) {
  if (item.los) {
    const los = findKpi(kpis, { kpi: 'level_of_service', level: item.level }, problem)
    return hasValue(los) ? `LOS ${los.los_grade}` : undefined
  }
  if (item.kpi === 'queue_length') {
    const vehicles = findKpi(kpis, { kpi: 'queue_length', level: item.level, unit: 'veh' }, problem)
    return hasValue(vehicles) ? `${formatKpiValue(vehicles)} vehicles` : undefined
  }
  return undefined
}

// Start time plus playback seconds as a clock: "07:46:35" (read from the
// text, like utils/format.js)
function clockAt(start, seconds) {
  const [h, m, s] = start.slice(11, 19).split(':').map(Number)
  const total = h * 3600 + m * 60 + s + Math.floor(seconds)
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(Math.floor(total / 3600) % 24)}:${pad(Math.floor(total / 60) % 60)}:${pad(total % 60)}`
}

export default RecommendationDetails
