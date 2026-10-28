import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import Badge from '../components/Badge'
import Breadcrumbs from '../components/Breadcrumbs'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import InfoList from '../components/InfoList'
import KpiTile from '../components/KpiTile'
import LosBadge from '../components/LosBadge'
import MethodTag from '../components/MethodTag'
import Notice from '../components/Notice'
import PageHeader from '../components/PageHeader'
import useElementWidth from '../hooks/useElementWidth'
import { getAlertDetails } from '../services/alertDetailsService'
import { shortDate, timeOf, timeRange } from '../utils/format'
import {
  KPI_DEFINITIONS,
  OVER_LIMIT,
  comparisonProps,
  displayUnit,
  formatKpiValue,
  hasValue,
  isOverLimit,
  kpiTileProps,
} from '../utils/kpi'
import { compactNumber, niceScale } from './trends/chartScale'
import './AlertDetails.css'

// Alert Details page, "/alerts/:problemId" (PBI 28).
// Opened from "View interventions" on an alert. It shows one problem: its
// alert details, how it developed, its baseline KPIs, and the ranked
// interventions, which open the Recommendation Details page.
//
// All values and the ranking come from alertDetailsService.js; the page
// never calculates a KPI. Try ?demo=empty or ?demo=error for other states.
//
// Note for the team: this page covers what AlertDetails.jsx was planned
// for, so that file may no longer be needed.

// The kinds of signal-timing change
const CATEGORY_LABELS = {
  signal_timing: 'Green split change',
  cycle_length: 'Cycle length change',
  phase_sequence: 'Phase sequence change',
}

// Each alert type's tag, and what its time means
const ALERT_TYPES = {
  current: { label: 'Current alert', when: 'Detected' },
  forecast: { label: 'Forecast alert', when: 'Expected from' },
  pattern: { label: 'Recurring alert', when: 'First seen' },
}

// Baseline tiles. Names match the Traffic Patterns & Trends page.
const APPROACH_KPIS = [
  { kpi: 'control_delay', level: 'approach', label: 'Control delay', los: true },
  { kpi: 'queue_length', level: 'approach', unit: 'm', label: 'Longest queue' },
  { kpi: 'queue_storage_ratio', level: 'approach', label: 'Storage ratio' },
  { kpi: 'throughput', level: 'approach', label: 'Throughput' },
]

const INTERSECTION_KPIS = [
  { kpi: 'control_delay', level: 'intersection', label: 'Control delay', los: true },
  { kpi: 'throughput', level: 'intersection', label: 'Throughput' },
]

// Rows of "Compare all options". unit tells apart the two queue lengths
// (m and veh). Names match the Trends page.
const COMPARE_ROWS = [
  { kpi: 'control_delay', level: 'approach', label: 'Control delay' },
  { kpi: 'level_of_service', level: 'approach', label: 'Level of service' },
  { kpi: 'queue_length', level: 'approach', unit: 'm', label: 'Longest queue' },
  { kpi: 'queue_length', level: 'approach', unit: 'veh', label: 'Longest queue' },
  { kpi: 'queue_storage_ratio', level: 'approach', label: 'Storage ratio' },
  { kpi: 'queue_duration', level: 'approach', label: 'Queue duration', hint: 'Average time stopped per vehicle' },
  { kpi: 'volume_to_capacity_ratio', level: 'approach', label: 'Highest v/c' },
  { kpi: 'throughput', level: 'approach', label: 'Throughput' },
  { kpi: 'control_delay', level: 'intersection', label: 'Control delay' },
  { kpi: 'level_of_service', level: 'intersection', label: 'Level of service' },
  { kpi: 'volume_to_capacity_ratio', level: 'intersection', label: 'Critical v/c' },
  { kpi: 'throughput', level: 'intersection', label: 'Throughput' },
]

// The three KPIs previewed on each intervention row (PBI 28)
const ROW_KPIS = [
  { kpi: 'queue_storage_ratio', level: 'approach', label: 'Storage ratio' },
  { kpi: 'control_delay', level: 'approach', label: 'Delay' },
  { kpi: 'queue_length', level: 'approach', unit: 'm', label: 'Queue' },
]

function AlertDetails() {
  const { problemId } = useParams()

  // The last result, with the problem it is for. A result for another
  // problem counts as still loading, so nothing has to be cleared.
  const [loaded, setLoaded] = useState({ problemId: null, data: null, error: null })
  const isCurrent = loaded.problemId === problemId
  const data = isCurrent ? loaded.data : null
  const error = isCurrent ? loaded.error : null

  // The problem whose options table is open, so it closes on another problem
  const [comparingFor, setComparingFor] = useState(null)
  const comparing = comparingFor === problemId

  useEffect(() => {
    let cancelled = false // true if the user leaves before the data arrives

    getAlertDetails(problemId)
      .then((result) => {
        if (!cancelled) setLoaded({ problemId, data: result, error: null })
      })
      .catch((err) => {
        if (!cancelled) setLoaded({ problemId, data: null, error: err.message })
      })

    return () => {
      cancelled = true
    }
  }, [problemId])

  const problem = data?.problem
  const type = problem && ALERT_TYPES[problem.alert_type]

  // "View interventions" in the header jumps to the list
  function scrollToOptions() {
    document.getElementById('alert-details-options-title')?.scrollIntoView({ behavior: 'smooth' })
  }

  const header = (
    <>
      <Breadcrumbs items={[{ label: 'Alerts', to: '/alerts' }, { label: problem?.title ?? 'Alert details' }]} />
      <PageHeader
        title={problem ? `${problem.title} on the ${problem.location.toLowerCase()}` : 'Alert details'}
        subtitle={problem?.intersection_name}
        actions={
          data?.recommendations.length > 0 && (
            <Button variant="secondary" onClick={scrollToOptions}>
              View interventions ({data.recommendations.length})
            </Button>
          )
        }
      />
    </>
  )

  if (error) {
    return (
      <>
        {header}
        <EmptyState variant="error" title="Alert details unavailable">
          {error}
        </EmptyState>
      </>
    )
  }

  if (!data) {
    return (
      <>
        {header}
        <EmptyState>Loading the alert and its recommendations…</EmptyState>
      </>
    )
  }

  const ranked = sortByRank(data.recommendations)
  const baseline = data.baseline.kpis

  return (
    <>
      {header}

      {data.isSample && (
        <Notice variant="warning" className="alert-details-notice">
          Sample data for layout only. These are not real simulation results.
        </Notice>
      )}

      {/* ---- Alert details, and how the problem developed ---- */}
      <div className="alert-details-overview">
        <section className="alert-details-overview-col" aria-labelledby="alert-details-details-title">
          <h2 id="alert-details-details-title" className="alert-details-section-title">
            Alert details
          </h2>
          <AlertRecord problem={problem} type={type} />
        </section>

        <section className="alert-details-overview-col" aria-labelledby="alert-details-history-title">
          <div className="alert-details-heading-row">
            <h2 id="alert-details-history-title" className="alert-details-section-title">
              {problem.alert_type === 'pattern' ? 'Recent weekdays' : historyTitle(problem.history)}
            </h2>
            {problem.alert_type === 'pattern' ? (
              <RecurrenceKey />
            ) : (
              <ChartKey hasForecast={problem.history?.points.some((p) => p.kind === 'forecast')} />
            )}
          </div>
          <Card>
            <ProblemHistory problem={problem} />
          </Card>
        </section>
      </div>

      {/* ---- The baseline ---- */}
      <section aria-labelledby="alert-details-baseline-title">
        <h2 id="alert-details-baseline-title" className="alert-details-section-title">
          <span
            className="alert-details-hint"
            tabIndex={0}
            data-hint="Conditions in this period without any change. Each intervention is compared with these values."
          >
            Baseline conditions
          </span>
        </h2>
        <div className={`alert-details-baseline alert-details-baseline-${problem.alert_type}`}>
          <StatGroup
            title={problem.location}
            items={APPROACH_KPIS}
            kpis={baseline}
            problem={problem}
          />
          <StatGroup
            title="Whole intersection"
            items={INTERSECTION_KPIS}
            kpis={baseline}
            problem={problem}
          />
        </div>
      </section>

      {/* ---- The recommended interventions ---- */}
      <section className="alert-details-options" aria-labelledby="alert-details-options-title">
        <header className="alert-details-options-header">
          <h2 id="alert-details-options-title" className="alert-details-options-title">
            Recommended interventions
          </h2>
          <Badge variant="count">{ranked.length}</Badge>
        </header>
        <p className="alert-details-options-text">
          Ranked by how well each is expected to solve this problem. Select one for details.
        </p>

        {ranked.length === 0 ? (
          <EmptyState title="No recommendation available">
            No recommendation is currently available for this problem.
          </EmptyState>
        ) : (
          <ol className="alert-details-list">
            {ranked.map((option) => (
              <li key={option.recommendation_id}>
                <OptionRow option={option} problem={problem} />
              </li>
            ))}
          </ol>
        )}

        {ranked.length > 1 && (
          <div className="alert-details-compare">
            <Button
              variant="secondary"
              onClick={() => setComparingFor(comparing ? null : problemId)}
              aria-expanded={comparing}
              aria-controls="alert-details-compare-table"
            >
              {comparing ? 'Hide comparison' : 'Compare all options'}
            </Button>
            {comparing && (
              <div id="alert-details-compare-table">
                <CompareTable
                  options={ranked}
                  baseline={data.baseline}
                  problem={problem}
                  problemId={problemId}
                />
              </div>
            )}
          </div>
        )}
      </section>
    </>
  )
}

// Every option next to the baseline, one row per KPI. The changes come
// from the KPI engine.
function CompareTable({ options, baseline, problem, problemId }) {
  const groups = [
    { level: 'approach', title: problem.location, rows: COMPARE_ROWS.filter((r) => r.level === 'approach') },
    { level: 'intersection', title: 'Whole intersection', rows: COMPARE_ROWS.filter((r) => r.level === 'intersection') },
  ]
  const columns = options.length + 2
  const cycle = (seconds) => (seconds != null ? `${seconds} s cycle` : 'Cycle unavailable')

  return (
    <Card className="alert-details-compare-box">
      <div className="alert-details-table-wrap" tabIndex={0} role="region" aria-label="All options compared with the baseline">
        <table className="alert-details-table">
          <thead>
            <tr>
              <th scope="col">
                <span className="alert-details-visually-hidden">KPI</span>
              </th>
              <th scope="col" className="alert-details-col-base">
                <span className="alert-details-col-head">
                  <span className="alert-details-rank alert-details-rank-sm alert-details-rank-base" aria-hidden="true">B</span>
                  <span>
                    <span className="alert-details-col-name">Baseline</span>
                    <span className="alert-details-col-meta">{cycle(baseline.cycle_length_s)}</span>
                  </span>
                </span>
              </th>
              {options.map((option) => (
                <th key={option.recommendation_id} scope="col">
                  <span className="alert-details-col-head">
                    <span
                      className={`alert-details-rank alert-details-rank-sm ${option.rank === 1 ? 'alert-details-rank-top' : ''}`}
                      aria-label={option.rank ? `Rank ${option.rank}` : 'Not ranked'}
                    >
                      {option.rank ?? '–'}
                    </span>
                    <span>
                      <Link
                        to={`/alerts/${problemId}/recommendations/${option.recommendation_id}`}
                        className="alert-details-col-name alert-details-col-link"
                      >
                        {option.title}
                      </Link>
                      <span className="alert-details-col-meta">{cycle(option.cycle_length_s)}</span>
                    </span>
                  </span>
                </th>
              ))}
            </tr>
          </thead>

          {groups.map((group) => (
            <tbody key={group.level}>
              <tr className="alert-details-table-group">
                <th scope="colgroup" colSpan={columns}>
                  {group.title}
                </th>
              </tr>
              {group.rows.map((row) => {
                const base = findKpi(baseline.kpis, row, problem)
                const unit = displayUnit(base?.unit)
                return (
                  <tr key={`${row.kpi}-${row.unit ?? ''}`}>
                    <th scope="row">
                      <span className="alert-details-row-label">
                        {row.label}
                        {unit && <span className="alert-details-unit"> ({unit})</span>}
                        {base?.method === 'hcm' && <MethodTag method="hcm" />}
                      </span>
                      {row.hint && <span className="alert-details-row-hint">{row.hint}</span>}
                    </th>
                    <td className="alert-details-col-base">
                      <TableValue result={base} />
                    </td>
                    {options.map((option) => (
                      <td key={option.recommendation_id}>
                        <TableValue result={findKpi(option.kpis, row, problem)} />
                        <TableChange comparison={findKpi(option.comparisons, row, problem)} />
                      </td>
                    ))}
                  </tr>
                )
              })}
            </tbody>
          ))}
        </table>
      </div>
    </Card>
  )
}

// A table value: a grade badge or a number, red when over its limit
function TableValue({ result }) {
  if (!hasValue(result)) {
    return (
      <span className="alert-details-muted" title={result?.reason ?? undefined}>
        {formatKpiValue(result)}
      </span>
    )
  }
  if (result.kpi === 'level_of_service') return <LosBadge grade={result.los_grade} />
  const over = isOverLimit(result)
  return (
    <span
      className={`alert-details-table-value ${over ? 'alert-details-value-over' : ''}`}
      title={over ? capitalize(OVER_LIMIT[result.kpi].label) : undefined}
    >
      {formatKpiValue(result)}
    </span>
  )
}

// The change against the baseline, in words as well as color. It comes
// from the engine's comparison, never from subtracting the two values.
function TableChange({ comparison }) {
  const { change, changeUnit, changeTone, changeNote } = comparisonProps(comparison)
  if (change === undefined) return null
  const arrow = change > 0 ? '↑' : change < 0 ? '↓' : ''
  return (
    <span className={`alert-details-table-change alert-details-change-${changeTone}`}>
      {arrow} {changeText(change, changeUnit, comparison.kpi)}
      {changeUnit} {changeNote}
    </span>
  )
}

// The alert's facts in a tinted sidebar, what happened beside them
function AlertRecord({ problem, type }) {
  const when =
    problem.alert_type === 'pattern'
      ? problem.detected_at && shortDate(problem.detected_at.slice(0, 10))
      : problem.detected_at && timeOf(problem.detected_at)

  const facts = [
    { label: 'Location', value: problem.location },
    { label: 'Period', value: timeRange(problem.interval_start, problem.interval_end), note: problem.period_label },
    { label: type?.when ?? 'Detected', value: when },
    problem.alert_type === 'pattern' && { label: 'How often', value: problem.recurrence },
  ].filter(Boolean)

  return (
    <div className="alert-details-record">
      <div className={`alert-details-record-side alert-details-record-side-${problem.alert_type}`}>
        <span className={`alert-details-type alert-details-type-${problem.alert_type}`}>
          {type?.label ?? 'Alert'}
        </span>
        <InfoList
          className="alert-details-record-facts"
          items={facts.map((fact) => ({
            label: fact.label,
            value: fact.value ? (
              <>
                {fact.value}
                {fact.note && <span className="alert-details-record-note">{fact.note}</span>}
              </>
            ) : undefined,
          }))}
        />
      </div>

      <div className="alert-details-record-main">
        <h3 className="alert-details-record-heading">What happened</h3>
        <p className="alert-details-record-description">{problem.description}</p>
        {problem.indicators?.length > 0 && (
          <>
            <h3 className="alert-details-record-heading">Flagged because</h3>
            <ul className="alert-details-checklist">
              {problem.indicators.map((indicator) => (
                <li key={indicator}>{indicator}</li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  )
}

function RecurrenceKey() {
  return (
    <span className="alert-details-chart-key">
      <span className="alert-details-key-item">
        <span className="alert-details-recur-swatch" aria-hidden="true" /> Problem recurred
      </span>
    </span>
  )
}

// The delay chart and forecast sentence, or a recurring alert's calendar
function ProblemHistory({ problem }) {
  if (problem.alert_type === 'pattern') return <RecurrenceView problem={problem} />
  return (
    <>
      <KpiHistory history={problem.history} problem={problem} />
      <p className="alert-details-forecast">
        <span className="alert-details-forecast-label">Forecast</span>
        {problem.forecast_outlook ?? (
          <span className="alert-details-muted">No forecast is available for this problem.</span>
        )}
      </p>
    </>
  )
}

// One group of baseline tiles. Flagged KPIs show "Flagged" as their tag;
// otherwise only HCM values show a method tag.
function StatGroup({ title, items, kpis, problem }) {
  return (
    <div className="alert-details-stat-group">
      <h3 className="alert-details-stat-group-title">{title}</h3>
      <div className="alert-details-stat-tiles">
        {items.map((item) => {
          const result = findKpi(kpis, item, problem)
          const flagged = isFlagged(item, problem)
          const tile = kpiTileProps(result)
          return (
            <KpiTile
              key={`${item.level}-${item.kpi}-${item.unit ?? ''}`}
              layout="stacked"
              label={item.label}
              {...tile}
              tag={flagged ? 'Flagged' : result?.method === 'simulation' ? undefined : tile.tag}
              detail={detailFor(item, kpis, problem)}
              className={flagged ? 'alert-details-tile-flagged' : ''}
            />
          )
        })}
      </div>
    </div>
  )
}

// One intervention row. The whole row links to its details.
function OptionRow({ option, problem }) {
  const available = option.status === 'ok'
  const isTop = option.rank === 1

  return (
    <Link
      to={`/alerts/${problem.problem_id}/recommendations/${option.recommendation_id}`}
      className={`alert-details-row ${isTop ? 'alert-details-row-top' : ''} ${available ? '' : 'alert-details-row-unavailable'}`}
    >
      <span className={`alert-details-rank ${isTop ? 'alert-details-rank-top' : ''}`} aria-hidden="true">
        {option.rank ?? '–'}
      </span>

      <span className="alert-details-row-name">
        <span className="alert-details-row-title">
          {option.title}
          {!available && <Badge>Not ranked</Badge>}
        </span>
        <span className="alert-details-row-meta">
          {CATEGORY_LABELS[option.category] ?? option.category}
        </span>
      </span>

      {available ? (
        <dl className="alert-details-row-kpis">
          {ROW_KPIS.map((item) => {
            const result = findKpi(option.kpis, item, problem)
            const comparison = comparisonProps(findKpi(option.comparisons, item, problem))
            const unit = displayUnit(result?.unit)
            return (
              <div key={`${item.kpi}-${item.unit ?? ''}`} className="alert-details-row-kpi">
                <dt>{item.label}</dt>
                <dd>
                  <span className={isOverLimit(result) ? 'alert-details-value-over' : ''}>
                    {formatKpiValue(result)}
                  </span>
                  {hasValue(result) && unit && <span className="alert-details-unit"> {unit}</span>}
                  {comparison.change !== undefined && (
                    <span className={`alert-details-change alert-details-change-${comparison.changeTone}`}>
                      {' '}
                      {comparison.change > 0 ? '↑' : comparison.change < 0 ? '↓' : ''}{' '}
                      {changeText(comparison.change, comparison.changeUnit, item.kpi)}
                      {comparison.changeUnit}
                    </span>
                  )}
                </dd>
              </div>
            )
          })}
        </dl>
      ) : (
        <span className="alert-details-row-reason">{option.reason}</span>
      )}

      <span className="alert-details-row-open">View details</span>
    </Link>
  )
}

// Legend for the delay chart
function ChartKey({ hasForecast }) {
  return (
    <span className="alert-details-chart-key">
      <span className="alert-details-key-item">
        <span className="alert-details-key-line" aria-hidden="true" /> Past
      </span>
      {hasForecast && (
        <span className="alert-details-key-item">
          <span className="alert-details-key-line alert-details-key-forecast" aria-hidden="true" /> Forecast
        </span>
      )}
    </span>
  )
}

// A recurring alert's recent weekdays (Sun–Thu), one row per week, with
// the days it recurred marked
const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu']

function RecurrenceView({ problem }) {
  const days = problem.recurrence_days ?? []
  if (days.length === 0) {
    return <EmptyState>No recurrence history is available for this problem.</EmptyState>
  }

  // Dates are read as text ("2026-10-07") so time zones cannot shift them
  const weeks = []
  days.forEach((day) => {
    const date = new Date(`${day.date}T00:00:00Z`)
    const weekday = date.getUTCDay() // 0 is Sunday
    if (weekday > 4) return
    const sunday = new Date(date.getTime() - weekday * 86400000).toISOString().slice(0, 10)
    let week = weeks.find((w) => w.sunday === sunday)
    if (!week) {
      week = { sunday, days: Array(5).fill(null) }
      weeks.push(week)
    }
    week.days[weekday] = day
  })

  const unit = displayUnit('s/veh')

  return (
    <>
      <p className="alert-details-recur-note">
        Delay (s/veh) on the {problem.location.toLowerCase()} at{' '}
        {timeRange(problem.interval_start, problem.interval_end)} each day.
      </p>
      <table className="alert-details-recur">
        <thead>
          <tr>
            <th scope="col">
              <span className="alert-details-visually-hidden">Week of</span>
            </th>
            {WEEKDAYS.map((name) => (
              <th key={name} scope="col">
                {name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week.sunday}>
              <th scope="row">{shortDate(week.sunday)}</th>
              {week.days.map((day, i) => {
                if (!day) return <td key={i} className="alert-details-recur-empty" />
                const result = { kpi: 'control_delay', unit: 's/veh', value: day.value, status: day.status }
                return (
                  <td
                    key={day.date}
                    className={day.occurred ? 'alert-details-recur-hit' : undefined}
                    title={day.reason ?? undefined}
                  >
                    <span className="alert-details-recur-date">{shortDate(day.date)}</span>
                    {hasValue(result) ? (
                      <span className="alert-details-recur-value">
                        {formatKpiValue(result)}
                        <span className="alert-details-unit alert-details-recur-unit"> {unit}</span>
                      </span>
                    ) : (
                      <span className="alert-details-muted alert-details-recur-missing">{formatKpiValue(result)}</span>
                    )}
                    {day.los_grade && <LosBadge grade={day.los_grade} />}
                    {day.occurred && <span className="alert-details-visually-hidden"> Problem recurred</span>}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

// Delay chart size, in pixels
const HEIGHT = 240
const MARGIN = { top: 20, right: 64, bottom: 26, left: 40 }

function historyTitle(history) {
  if (history?.kpi === 'control_delay') return 'Delay over time'
  return `${KPI_DEFINITIONS[history?.kpi]?.label ?? 'History'} over time`
}

// The problem approach's delay per 15-minute interval: the past two hours,
// then the forecast (dashed). Missing intervals are gaps, never zero.
// Hover or use the arrow keys to read a value.
function KpiHistory({ history, problem }) {
  const [hoverIndex, setHoverIndex] = useState(null)
  const [ref, width] = useElementWidth()

  const points = history?.points ?? []
  if (!points.some((p) => p.status === 'ok' && p.value != null)) {
    return <EmptyState>No history is available for this problem.</EmptyState>
  }

  const unit = displayUnit(history.unit)
  const limit = OVER_LIMIT[history.kpi]?.limit
  const lastIndex = points.length - 1
  // As a KpiResult, so utils/kpi.js can format it
  const asResult = (p) => ({ kpi: history.kpi, unit: history.unit, value: p.value, status: p.status })

  // ---- Scales: turn a point's place and value into pixels ----------------
  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 10)
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const step = plotWidth / Math.max(lastIndex, 1)
  const values = points.filter((p) => p.value != null).map((p) => p.value)
  const { max, ticks } = niceScale(Math.max(...values, limit ?? 0) * 1.08)
  const x = (index) => MARGIN.left + index * step
  const y = (value) => MARGIN.top + plotHeight - (value / max) * plotHeight

  // The past line breaks at missing intervals; the forecast continues it
  const pastSegments = []
  let current = []
  points.forEach((p, i) => {
    if (p.kind !== 'past') return
    if (p.value != null) current.push(`${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)
    else if (current.length) {
      pastSegments.push(current)
      current = []
    }
  })
  if (current.length) pastSegments.push(current)

  const firstForecast = points.findIndex((p) => p.kind === 'forecast')
  const forecastPath =
    firstForecast >= 0
      ? points
          .slice(Math.max(firstForecast - 1, 0))
          .filter((p) => p.value != null)
          .map((p) => {
            const i = points.indexOf(p)
            return `${x(i).toFixed(1)},${y(p.value).toFixed(1)}`
          })
      : []

  // The analysis period, shaded
  const windowIndex = points.findIndex((p) => p.interval_start === problem.interval_start)
  const bandLeft = Math.max(x(windowIndex) - step / 2, MARGIN.left)
  const bandRight = Math.min(x(windowIndex) + step / 2, MARGIN.left + plotWidth)

  // Time labels every 30 min, or every hour when narrow
  const labelEvery = plotWidth < 360 ? 4 : 2

  function handlePointer(event) {
    const box = event.currentTarget.getBoundingClientRect()
    const index = Math.round((event.clientX - box.left - MARGIN.left) / step)
    setHoverIndex(Math.min(Math.max(index, 0), lastIndex))
  }

  function handleKey(event) {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      const move = event.key === 'ArrowRight' ? 1 : -1
      setHoverIndex((i) => Math.min(Math.max((i ?? (move > 0 ? -1 : lastIndex + 1)) + move, 0), lastIndex))
    }
    if (event.key === 'Escape') setHoverIndex(null)
  }

  const hovered = hoverIndex === null ? null : points[hoverIndex]

  return (
    <div
      ref={ref}
      className="alert-details-chart"
      tabIndex={0}
      role="img"
      aria-label={`${KPI_DEFINITIONS[history.kpi]?.label} on the ${problem.location.toLowerCase()}, per 15-minute interval${
        firstForecast >= 0 ? ', then the forecast' : ''
      }. Use the arrow keys to read each interval.`}
      onPointerMove={handlePointer}
      onPointerLeave={() => setHoverIndex(null)}
      onKeyDown={handleKey}
      onBlur={() => setHoverIndex(null)}
    >
      {width > 0 && (
        <svg width={width} height={HEIGHT} aria-hidden="true">
          {windowIndex >= 0 && (
            <g>
              <rect
                className="alert-details-chart-window"
                x={bandLeft}
                y={MARGIN.top}
                width={bandRight - bandLeft}
                height={plotHeight}
              />
              <text
                className="alert-details-chart-note"
                x={x(windowIndex)}
                y={MARGIN.top - 6}
                textAnchor="middle"
              >
                Period
              </text>
            </g>
          )}

          {ticks.map((tick) => (
            <g key={tick}>
              <line className="alert-details-chart-grid" x1={MARGIN.left} x2={MARGIN.left + plotWidth} y1={y(tick)} y2={y(tick)} />
              <text className="alert-details-chart-axis" x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                {compactNumber(tick)}
              </text>
            </g>
          ))}

          {/* The standard limit, labelled on the right */}
          {limit != null && (
            <g>
              <line className="alert-details-chart-limit" x1={MARGIN.left} x2={MARGIN.left + plotWidth} y1={y(limit)} y2={y(limit)} />
              <text className="alert-details-chart-limit-label" x={MARGIN.left + plotWidth + 6} y={y(limit)} dy="0.32em">
                Limit {limit.toFixed(1)}
              </text>
            </g>
          )}

          {points.map((p, i) =>
            i % labelEvery === 0 ? (
              <text
                key={p.interval_start}
                className="alert-details-chart-axis"
                x={x(i)}
                y={HEIGHT - 6}
                textAnchor={i === 0 ? 'start' : 'middle'}
              >
                {timeOf(p.interval_start)}
              </text>
            ) : null,
          )}

          {/* Missing intervals: a light band, so the gap reads as missing */}
          {points.map((p, i) =>
            p.value == null ? (
              <rect
                key={`gap-${p.interval_start}`}
                className="alert-details-chart-missing"
                x={x(i) - step / 2}
                y={MARGIN.top}
                width={step}
                height={plotHeight}
              />
            ) : null,
          )}

          {pastSegments.map((segment, i) => (
            <polyline key={i} className="alert-details-chart-line" points={segment.join(' ')} />
          ))}
          {forecastPath.length > 1 && (
            <polyline className="alert-details-chart-line alert-details-chart-forecast" points={forecastPath.join(' ')} />
          )}

          {hovered && (
            <g>
              <line className="alert-details-chart-crosshair" x1={x(hoverIndex)} x2={x(hoverIndex)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} />
              {hovered.value != null && (
                <circle className="alert-details-chart-dot" cx={x(hoverIndex)} cy={y(hovered.value)} r="5" />
              )}
            </g>
          )}
        </svg>
      )}

      {hovered && (
        <div
          className="alert-details-chart-tooltip"
          style={{
            left: `${x(hoverIndex)}px`,
            transform: `translateX(${hoverIndex > lastIndex * 0.6 ? 'calc(-100% - 12px)' : '12px'})`,
          }}
        >
          <strong className={hovered.value == null ? 'alert-details-muted' : undefined}>
            {formatKpiValue(asResult(hovered))}
            {hovered.value != null && unit && ` ${unit}`}
            {hovered.los_grade && ` · LOS ${hovered.los_grade}`}
          </strong>
          <span>
            {timeRange(hovered.interval_start, hovered.interval_end)} ·{' '}
            {hovered.kind === 'forecast' ? 'Forecast' : 'Past'}
          </span>
          {hovered.value == null && hovered.reason && (
            <span className="alert-details-chart-reason">{hovered.reason}</span>
          )}
          {isOverLimit(asResult(hovered)) && (
            <span className="alert-details-chart-flag">{capitalize(OVER_LIMIT[history.kpi].label)}</span>
          )}
        </div>
      )}
    </div>
  )
}

// ---- Small helpers ----------------------------------------------------------

// Whether the alert was flagged for this KPI
function isFlagged(item, problem) {
  return problem.triggered_by?.some(
    (t) => t.kpi === item.kpi && t.level === item.level && (!t.unit || t.unit === item.unit),
  )
}

// A change without its sign, keeping the KPI's decimals (0.10, not 0.1)
function changeText(change, changeUnit, kpi) {
  const decimals = changeUnit === '%' ? 0 : KPI_DEFINITIONS[kpi]?.decimals ?? 0
  return Math.abs(change).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

// Best rank first, unranked options last. The backend decides the rank;
// this only sorts.
function sortByRank(recommendations) {
  return [...recommendations].sort((a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity))
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

function capitalize(text) {
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export default AlertDetails
