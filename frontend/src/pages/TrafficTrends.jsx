import { useEffect, useState } from 'react'
import AlertList from '../components/AlertList'
import Badge from '../components/Badge'
import EmptyState from '../components/EmptyState'
import KpiGroup from '../components/KpiGroup'
import KpiTile from '../components/KpiTile'
import LocationInfoCard from '../components/LocationInfoCard'
import Notice from '../components/Notice'
import PageHeader from '../components/PageHeader'
import SegmentedControl from '../components/SegmentedControl'
import Select from '../components/Select'
import { EmptyPeriodError, getTrends } from '../services/trendsService'
import { formatKpiValue, kpiTileProps } from '../utils/kpi'
import { shortDate, timeOf, timeRange } from '../utils/format'
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

  const header = (
    <PageHeader
      title="Traffic Patterns & Trends"
      subtitle={data && describePeriod(data.period, periodDays)}
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

  const note = `vs prev. ${periodDays} days`

  return (
    <>
      {header}

      {data.isSample && (
        <Notice variant="warning" className="trends-notice">
          Sample data for layout only: all values on this page are illustrative, not
          simulation results.
        </Notice>
      )}

      {/* While new data loads, the old data stays on screen, faded */}
      <div className={`trends-layout ${loading ? 'is-loading' : ''}`} aria-busy={loading}>
        <aside className="trends-side">
          <LocationInfoCard intersection={data.intersection} />

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
        </aside>

        <div className="trends-main">
          <KpiRow
            summary={data.summary}
            dayType={dayType}
            approachId={approachId}
            periodDays={periodDays}
            note={note}
          />

          <div className="trends-row trends-row-wide-left">
            <TrendChart trend={data.trend} />
            <WeekdayWeekendChart pairs={data.weekdayWeekend} />
          </div>

          <CongestionHeatmap cells={data.heatmap} />

          <div className="trends-row trends-row-wide-left">
            <ThresholdChart thresholds={data.thresholds} />
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

function KpiRow({ summary, dayType, approachId, periodDays, note }) {
  const delay = summary.control_delay
  const queue = summary.queue_length
  const vc = summary.volume_to_capacity_ratio
  const grade = summary.level_of_service.current.los_grade
  const peak = summary.peakWindow
  const dayWord = DAY_WORDS[dayType]

  // What the tiles share is said once by KpiGroup, so the tiles leave out the tag and the
  // "vs prev." note
  const results = [delay.current, queue.current, summary.throughput.current, vc.current]

  return (
    <KpiGroup compared={`the previous ${periodDays} days`} results={results}>
      <div className="kpi-row">
        <KpiTile
          layout="stacked"
          label="Avg control delay"
          detail={grade ? `LOS ${grade}` : 'LOS unavailable'}
          {...kpiTileProps(delay.current, delay.previous)}
          tag={undefined}
        />
        <KpiTile
          layout="stacked"
          label="95th-pct queue, worst movement"
          detail={`${queue.worst.label} · storage ratio ${formatKpiValue(queue.worst.storageRatio)}`}
          {...kpiTileProps(queue.current, queue.previous)}
          tag={undefined}
        />
        <KpiTile
          layout="stacked"
          label="Avg throughput"
          detail={approachId === 'all' ? 'All signalized movements' : 'All movements of this approach'}
          {...kpiTileProps(summary.throughput.current, summary.throughput.previous)}
          tag={undefined}
        />
        <KpiTile
          layout="stacked"
          label={approachId === 'all' ? 'Critical v/c, peak 15 min' : 'Highest v/c, peak 15 min'}
          detail={`${dayWord} ${timeRange(vc.current.interval_start, vc.current.interval_end)}`}
          {...kpiTileProps(vc.current, vc.previous)}
          tag={undefined}
        />
        <KpiTile
          layout="stacked"
          label="Peak congestion window"
          value={timeOf(peak.interval_start)}
          unit={`–${timeOf(peak.interval_end)}`}
          detail={`Highest avg control delay, ${dayWord.toLowerCase()}`}
          changeNote={peak.sameAsPrevious ? `Same window as ${note.replace('vs ', '')}` : 'Moved since the previous period'}
        />
      </div>
    </KpiGroup>
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

// "15 Sep – 14 Oct 2026 · 2,880 fifteen-minute intervals · compared with the previous 30 days"
function describePeriod(period, periodDays) {
  const range = `${shortDate(period.start)} – ${shortDate(period.end)} ${period.end.slice(0, 4)}`
  return `${range} · ${period.intervalCount.toLocaleString('en-US')} fifteen-minute intervals · compared with the previous ${periodDays} days`
}

export default TrafficTrends