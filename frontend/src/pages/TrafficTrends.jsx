import { useEffect, useState } from 'react'
import AlertList from '../components/AlertList'
import Badge from '../components/Badge'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import KpiGroup from '../components/KpiGroup'
import KpiTile from '../components/KpiTile'
import LocationInfoCard from '../components/LocationInfoCard'
import PageHeader from '../components/PageHeader'
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

function TrafficTrends() {
  // The filters. Changing any of them loads the data again.
  // The page opens on 7 days: the longest period with enough simulated days
  // today (docs/kpi_engine.md, section 17.6).
  const [periodDays, setPeriodDays] = useState(7)
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

  const header = (
    <PageHeader
      title="Traffic Patterns & Trends"
      // The period of the data on screen: none while an error is shown instead
      subtitle={data && !error ? describePeriod(data.period) : undefined}
      actions={
        <>
          <Select
            label="Time period"
            options={PERIOD_OPTIONS}
            value={String(periodDays)}
            onChange={(value) => setPeriodDays(Number(value))}
          />
          <SegmentedControl
            ariaLabel="Day type"
            options={DAY_TYPE_OPTIONS}
            value={dayType}
            onChange={setDayType}
          />
          <Select
            label="Approach"
            options={approachOptions}
            value={approachId}
            onChange={setApproachId}
          />
        </>
      }
    />
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
      <div className={`trends-layout ${loading ? 'is-loading' : ''}`} aria-busy={loading}>
        <aside className="trends-side">
          <LocationInfoCard intersection={data.intersection} />

          {data.recurringAlerts ? (
            <div>
              <AlertList
                title="Recurring problem alerts"
                alerts={data.recurringAlerts.map(toAlertListItem)}
                emptyMessage="No recurring traffic problems are currently identified."
              />
              <p className="trends-side-note">
                A problem counts as recurring when its rule is exceeded in the same time
                window on at least half the days in the period.
              </p>
            </div>
          ) : (
            <NotAvailableYet title="Recurring problem alerts" />
          )}
        </aside>

        <div className="trends-main">
          <KpiRow summary={data.summary} dayType={dayType} approachId={approachId} />

          <div className="trends-row trends-row-wide-left">
            <TrendChart trend={data.trend} />
            <WeekdayWeekendChart pairs={data.weekdayWeekend} />
          </div>

          <CongestionHeatmap cells={data.heatmap} />

          <div className="trends-row trends-row-wide-left">
            {data.thresholds ? (
              <ThresholdChart thresholds={data.thresholds} />
            ) : (
              <NotAvailableYet title="Threshold exceedance by time window" />
            )}
            <LosDistribution rows={data.losDistribution} />
          </div>

          <BreakdownTable
            filters={{ periodDays, dayType, approachId }}
            windows={data.breakdownWindows}
          />
        </div>
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
          detail={
            queue.worst
              ? `${queue.worst.label} · storage ratio ${formatKpiValue(queue.worst.storageRatio)}`
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
        Recurring-problem detection is a later feature (backlog items 24 and 25).
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
    detailsTo: alert.problemId ? `/alerts/${alert.problemId}` : undefined,
  }
}

// "3 Nov – 9 Nov 2026 · based on 7 of 7 days · 672 fifteen-minute intervals"
function describePeriod(period) {
  const range = `${shortDate(period.start)} – ${shortDate(period.end)} ${period.end.slice(0, 4)}`
  return `${range} · based on ${period.daysUsed} of ${period.daysExpected} days · ${period.intervalCount.toLocaleString('en-US')} fifteen-minute intervals`
}

export default TrafficTrends