import { useEffect, useState } from 'react'
import AlertList from '../components/AlertList'
import Badge from '../components/Badge'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import InfoTip from '../components/InfoTip'
import KpiGroup from '../components/KpiGroup'
import KpiTile from '../components/KpiTile'
import LocationInfoCard from '../components/LocationInfoCard'
import SegmentedControl from '../components/SegmentedControl'
import Select from '../components/Select'
import { EmptyPeriodError, getTrends } from '../services/trendsService'
import { formatKpiValue, kpiTileProps } from '../utils/kpi'
import { dayAndDate, shortDate, timeOf, timeRange } from '../utils/format'
import BreakdownTable from './trends/BreakdownTable'
import CongestionHeatmap from './trends/CongestionHeatmap'
import LosDistribution from './trends/LosDistribution'
import ThresholdChart from './trends/ThresholdChart'
import TrendChart from './trends/TrendChart'
import WeekdayWeekendChart from './trends/WeekdayWeekendChart'
import './TrafficTrends.css'

// Choices for the filters at the top of the page
const PERIOD_OPTIONS = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
]

const DAY_TYPE_OPTIONS = [
  { value: 'all', label: 'All days' },
  { value: 'weekdays', label: 'Weekdays (Sun–Thu)' },
  { value: 'weekends', label: 'Weekends (Fri–Sat)' },
]

// How a problem is judged recurring, behind the info button of the recurring alerts
const RECURRING_RULE =
  'A problem counts as recurring when its rule is exceeded in the same time window on at ' +
  'least half the days in the period.'

// The three tabs of the page, as in the sitemap
const TABS = [
  { value: 'summary', label: 'Summary', hint: 'KPIs and trends' },
  { value: 'patterns', label: 'Patterns', hint: 'When congestion happens' },
  { value: 'breakdown', label: 'Breakdown', hint: 'By approach and movement' },
]

function TrafficTrends() {
  const [tab, setTab] = useState('summary')
  // The filters. Changing any of them loads the data again.
  // The page opens on 30 days: a 30-day view still has data when a day is
  // missing, a 7-day view does not (docs/kpi_engine.md, sections 17.6 and 17.8)
  const [periodDays, setPeriodDays] = useState(30)
  const [dayType, setDayType] = useState('all')
  const [approachId, setApproachId] = useState('all')

  const [data, setData] = useState(null) // the last data that arrived
  const [error, setError] = useState(null) // the error, if loading failed
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)

    getTrends({ periodDays, dayType, approachId })
      .then((result) => {
        if (cancelled) return
        setData(result)
        setError(null)
      })
      .catch((err) => {
        if (cancelled) return
        setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [periodDays, dayType, approachId])

  const approachOptions = [
    { value: 'all', label: 'All' },
    ...(data?.approaches ?? []).map((a) => ({ value: a.approach_id, label: a.label })),
  ]

  // The tabs and the filters, the same on every tab. The filters apply to all three tabs.
  const header = (
    <>
      <h1 className="trends-visually-hidden">Traffic Patterns &amp; Trends</h1>
      <div className="trends-tabs" role="tablist" aria-label="Traffic Patterns & Trends">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            role="tab"
            id={`trends-tab-${t.value}`}
            aria-selected={tab === t.value}
            aria-controls="trends-panel"
            className={`trends-tab${tab === t.value ? ' trends-tab-active' : ''}`}
            onClick={() => setTab(t.value)}
          >
            <span className="trends-tab-label">{t.label}</span>
            <span className="trends-tab-hint">{t.hint}</span>
          </button>
        ))}
      </div>

      <div className="trends-filters">
        <span className="trends-period-field">
          <Select
            label="Time period"
            options={PERIOD_OPTIONS}
            value={String(periodDays)}
            onChange={(value) => setPeriodDays(Number(value))}
          />
          {/* The days the data on screen covers: none while an error is shown instead */}
          {data && !error && (
            <InfoTip label="About the data in this period">{describePeriod(data.period)}</InfoTip>
          )}
        </span>
        <Select
          label="Approach"
          options={approachOptions}
          value={approachId}
          onChange={setApproachId}
        />
        <SegmentedControl
          ariaLabel="Day type"
          className="trends-day-type"
          options={DAY_TYPE_OPTIONS}
          value={dayType}
          onChange={setDayType}
        />
      </div>
    </>
  )

  // Nothing to show yet: the very first load
  if (!data && !error) {
    return (
      <>
        {header}
        <EmptyState>Loading performance data…</EmptyState>
      </>
    )
  }

  // Loading failed, or there is no data for these filters
  if (error) {
    return (
      <>
        {header}
        {error instanceof EmptyPeriodError ? (
          <EmptyState title="No performance data available">{error.message}</EmptyState>
        ) : (
          <EmptyState variant="error" title="Performance data unavailable">
            {error.message}
          </EmptyState>
        )}
      </>
    )
  }

  return (
    <>
      {header}

      {/* While new data loads, the old data stays on screen, faded */}
      <div
        id="trends-panel"
        role="tabpanel"
        aria-labelledby={`trends-tab-${tab}`}
        className={`trends-panel ${loading ? 'is-loading' : ''}`}
        aria-busy={loading}
      >
        {tab === 'summary' && (
          <>
            <KpiRow summary={data.summary} dayType={dayType} approachId={approachId} />

            <div className="trends-summary">
              <div className="trends-side">
                <LocationInfoCard intersection={data.intersection} />

                {data.recurringAlerts ? (
                  <AlertList
                    title="Recurring problem alerts"
                    alerts={data.recurringAlerts.map(toAlertListItem)}
                    emptyMessage="No recurring traffic problems are currently identified."
                    info={RECURRING_RULE}
                  />
                ) : (
                  <NotAvailableYet title="Recurring problem alerts" />
                )}
              </div>

              <TrendChart trend={data.trend} />
              <WeekdayWeekendChart pairs={data.weekdayWeekend} />
            </div>
          </>
        )}

        {tab === 'patterns' && (
          <div className="trends-patterns">
            <div className="trends-patterns-main">
              <CongestionHeatmap cells={data.heatmap} />
              {data.thresholds ? (
                <ThresholdChart thresholds={data.thresholds} />
              ) : (
                <NotAvailableYet title="Threshold exceedance by time window" />
              )}
            </div>
            <LosDistribution rows={data.losDistribution} />
          </div>
        )}

        {tab === 'breakdown' && (
          <BreakdownTable
            filters={{ periodDays, dayType, approachId }}
            windows={data.breakdownWindows}
          />
        )}
      </div>
    </>
  )
}

// ---- The five KPI tiles ----------------------------------------------------

// The values are over the whole period; there is no comparison with an
// earlier period (the trend chart shows the direction day by day).
function KpiRow({ summary, dayType, approachId }) {
  const delay = summary.control_delay.current
  const queue = summary.queue_length
  const vc = summary.volume_to_capacity_ratio.current
  const grade = summary.level_of_service.current.los_grade
  const peak = summary.peakWindow
  const dayWord = DAY_WORDS[dayType]

  // How the values were measured is said once by KpiGroup, so the tiles leave out the tag
  const results = [delay, queue.current, summary.throughput.current, vc]

  return (
    <KpiGroup results={results}>
      <div className="kpi-row trends-kpi-row">
        <KpiTile
          layout="stacked"
          label="Avg control delay"
          detail={grade ? `LOS ${grade}` : 'LOS unavailable'}
          {...kpiTileProps(delay)}
          tag={undefined}
        />
        <KpiTile
          layout="stacked"
          label="95th-pct queue, worst movement"
          // The storage ratio is shown only when it has a value: most lanes
          // have no storage length yet, as on Current Traffic
          detail={
            queue.worst
              ? queue.worst.storageRatio?.status === 'ok'
                ? `${queue.worst.label} · storage ratio ${formatKpiValue(queue.worst.storageRatio)}`
                : queue.worst.label
              : undefined
          }
          {...kpiTileProps(queue.current)}
          tag={undefined}
        />
        <KpiTile
          layout="stacked"
          label="Avg throughput"
          detail={approachId === 'all' ? 'All movements' : 'All movements of this approach'}
          {...kpiTileProps(summary.throughput.current)}
          tag={undefined}
        />
        <KpiTile
          layout="stacked"
          label={approachId === 'all' ? 'Critical v/c, peak 15 min' : 'Highest v/c, peak 15 min'}
          // The peak is one real interval, so its day is shown
          detail={
            vc.status === 'ok'
              ? `${dayAndDate(vc.interval_start.slice(0, 10))}, ${timeRange(vc.interval_start, vc.interval_end)}`
              : undefined
          }
          {...kpiTileProps(vc)}
          tag={undefined}
        />
        <KpiTile
          layout="stacked"
          label="Peak congestion window"
          value={peak.status === 'ok' ? timeOf(peak.interval_start) : null}
          unit={peak.status === 'ok' ? `–${timeOf(peak.interval_end)}` : undefined}
          status={peak.status === 'ok' ? undefined : peak.status}
          reason={peak.status === 'ok' ? undefined : peak.reason}
          detail={peak.status === 'ok' ? `Highest avg control delay, ${dayWord.toLowerCase()}` : undefined}
        />
      </div>
    </KpiGroup>
  )
}

// A panel whose data comes from a later feature
function NotAvailableYet({ title }) {
  return (
    <Card title={title}>
      <EmptyState title="Not available yet">
        Coming in a later release.
      </EmptyState>
    </Card>
  )
}

// ---- Helpers ---------------------------------------------------------------

const DAY_WORDS = { all: 'All days', weekdays: 'Weekdays', weekends: 'Weekends' }

// One recurring alert from the service, as AlertList expects it
function toAlertListItem(alert) {
  return {
    id: alert.id,
    title: alert.title,
    details: [
      { label: 'Location', value: alert.location },
      { label: 'When', value: alert.when },
      { label: 'How often', value: `${alert.daysSeen} of ${alert.daysTotal} days` },
      { label: 'Rule', value: alert.rule },
      {
        label: 'Status',
        value: alert.status === 'active' ? <Badge variant="warning">Active</Badge> : undefined,
      },
    ],
  }
}

// "3 Nov – 9 Nov 2026 · based on 7 of 7 days · 672 fifteen-minute intervals"
function describePeriod(period) {
  const range = `${shortDate(period.start)} – ${shortDate(period.end)} ${period.end.slice(0, 4)}`
  return `${range} · based on ${period.daysUsed} of ${period.daysExpected} days · ${period.intervalCount.toLocaleString('en-US')} fifteen-minute intervals`
}

export default TrafficTrends
