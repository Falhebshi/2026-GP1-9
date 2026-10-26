import { useState } from 'react'
import AlertCard from '../components/AlertCard'
import AlertList from '../components/AlertList'
import ApproachPanel from '../components/ApproachPanel'
import Badge from '../components/Badge'
import BrandMark from '../components/BrandMark'
import Breadcrumbs from '../components/Breadcrumbs'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import HistoricalTimeline from '../components/HistoricalTimeline'
import InfoList from '../components/InfoList'
import KpiTile from '../components/KpiTile'
import LocationInfoCard from '../components/LocationInfoCard'
import LocationSummary from '../components/LocationSummary'
import LosBadge, { GRADES } from '../components/LosBadge'
import MethodTag from '../components/MethodTag'
import Notice from '../components/Notice'
import PageHeader from '../components/PageHeader'
import PlaybackBar from '../components/PlaybackBar'
import SegmentedControl from '../components/SegmentedControl'
import Select from '../components/Select'
import SimulationViewport from '../components/SimulationViewport'
import usePlayback from '../hooks/usePlayback'
import {
  notApplicableResult,
  sampleResult,
  unavailableResult,
} from '../services/sampleKpiResults'
import { kpiTileProps } from '../utils/kpi'
import './ComponentPreview.css'

// Example choices for the Select examples (fake data)
const periodOptions = [
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
]

const intersectionOptions = [
  { value: 'a', label: 'Intersection A' },
  { value: 'b', label: 'Intersection B' },
]

const metricOptions = [
  { value: 'delay', label: 'Avg Control Delay' },
  { value: 'queue', label: 'Avg Queue Length' },
  { value: 'speed', label: 'Avg Speed' },
]

// Example choices for the SegmentedControl examples (fake data)
const dayTypeOptions = [
  { value: 'all', label: 'All days' },
  { value: 'weekdays', label: 'Weekdays' },
  { value: 'weekends', label: 'Weekends' },
]

const mapViewOptions = [
  { value: 'segments', label: 'Segments' },
  { value: 'heatmap', label: 'Heatmap' },
]

const speedOptions = [
  { value: '5', label: 'x5' },
  { value: '10', label: 'x10' },
  { value: '20', label: 'x20' },
]

// Example KPI results, shaped exactly like the backend's KpiResult (fake data).
// "current" is this period, "previous" the period before, for the change.
const exampleResults = {
  delay: {
    current: { kpi: 'control_delay', method: 'simulation', unit: 's/veh', value: 31.4, status: 'ok' },
    previous: { kpi: 'control_delay', method: 'simulation', unit: 's/veh', value: 30.2, status: 'ok' },
  },
  throughput: {
    current: { kpi: 'throughput', method: 'simulation', unit: 'veh/h', value: 3210, status: 'ok' },
    previous: { kpi: 'throughput', method: 'simulation', unit: 'veh/h', value: 3117, status: 'ok' },
  },
  vc: {
    current: { kpi: 'volume_to_capacity_ratio', method: 'hcm', unit: 'ratio', value: 0.94, status: 'ok' },
    previous: { kpi: 'volume_to_capacity_ratio', method: 'hcm', unit: 'ratio', value: 0.91, status: 'ok' },
  },
  storage: {
    current: {
      kpi: 'queue_storage_ratio', method: 'simulation', unit: 'ratio', value: null,
      status: 'unavailable', reason: 'Storage length is not known for this lane.',
    },
  },
  losRight: {
    current: {
      kpi: 'level_of_service', method: 'simulation', unit: 'grade', value: null,
      status: 'not_applicable', reason: 'Right turns on the slip road are not signal controlled.',
    },
  },
}

// Example rows for the InfoList examples (fake data)
const locationItems = [
  { label: 'Name', value: 'Intersection A' },
  { label: 'Area', value: 'Al Olaya' },
  { label: 'Approaches', value: '4 approaches' },
  { label: 'Signal type', value: 'Adaptive signal' },
]

const alertDetailItems = [
  { label: 'Location', value: 'North approach' },
  { label: 'When', value: 'Weekdays, 07:30-09:00' },
  { label: 'How often', value: '4 of 5 days' },
  { label: 'Status', value: <Badge variant="warning">Active</Badge> },
]

const incompleteItems = [
  { label: 'Name', value: 'Intersection B' },
  { label: 'Approaches', value: 3 },
  { label: 'Signal type' }, // no value: shows "Unavailable"
]

// Example intersections for the LocationInfoCard examples (fake data)
const fullIntersection = {
  name: 'Intersection A',
  area: 'Al Olaya',
  approaches: 4,
  signalType: 'Adaptive signal',
}

// Example approaches for the ApproachPanel example (fake data), in the KpiResult shape the
// backend sends. exampleKpis takes delay, LOS, v/c, queue and flow; SLIP marks the signal
// measures as not applicable. Storage ratio is left unavailable to show that state.
const EXAMPLE_INTERVAL = ['2026-10-14T05:00:00Z', '2026-10-14T05:15:00Z']
const SLIP = 'slip'

function exampleKpis(element, [delay, los, vc, queue, throughput]) {
  const result = (kpi, value) =>
    value === SLIP
      ? notApplicableResult(kpi, element, EXAMPLE_INTERVAL, 'Uncontrolled right turn on a slip lane.')
      : sampleResult(kpi, value, element, EXAMPLE_INTERVAL)
  return {
    control_delay: result('control_delay', delay),
    level_of_service: result('level_of_service', los),
    volume_to_capacity_ratio: result('volume_to_capacity_ratio', vc),
    queue_length: result('queue_length', queue),
    throughput: result('throughput', throughput),
    capacity: result('capacity', vc === SLIP ? SLIP : 1200),
    saturation_flow_rate: result('saturation_flow_rate', vc === SLIP ? SLIP : 1800),
    queue_duration: result('queue_duration', 30),
    queue_storage_ratio: unavailableResult(
      'queue_storage_ratio',
      element,
      EXAMPLE_INTERVAL,
      'Storage length is not known.',
    ),
  }
}

function exampleApproach(approach_id, arm, road, values, movements) {
  return {
    approach_id,
    arm,
    road,
    kpis: exampleKpis({ level: 'approach', id: approach_id }, values),
    movements: movements.map(([movement_id, label, movementValues]) => ({
      movement_id,
      label,
      kpis: exampleKpis({ level: 'movement', id: movement_id }, movementValues),
    })),
  }
}

const exampleApproaches = [
  exampleApproach('APP_E', 'East', 'Main road', [44, 'D', 0.88, 118, 1540], [
    ['MOV_E_W', 'Through', [40, 'D', 0.82, 96, 1040]],
    ['MOV_E_S', 'Left', [71, 'E', 0.94, 118, 500]],
  ]),
  exampleApproach('APP_N', 'North', 'Side road', [64, 'F', 1.04, 168, 790], [
    ['MOV_N_E', 'Left', [64, 'F', 1.04, 168, 700]],
    ['MOV_N_W_SLIP', 'Right (slip lane)', [8, SLIP, SLIP, 18, 90]],
  ]),
]

const partialIntersection = {
  name: 'Intersection B',
  approaches: 3,
}

// Example alerts for the AlertList examples (fake data)

// Simple alerts, as on Current Traffic: a subtitle, no details to open
const activeAlerts = [
  {
    id: 'a1',
    title: 'Queue spillback',
    subtitle: 'North approach · 2 min ago',
    detailsTo: '/alerts/1',
  },
  {
    id: 'a2',
    title: 'Low average speed',
    subtitle: 'East approach · 7 min ago',
    detailsTo: '/alerts/2',
  },
  {
    id: 'a3',
    title: 'High V/C ratio',
    subtitle: 'West approach · 11 min ago',
    // no detailsTo: this alert shows no link
  },
]

// Alerts with details, as on Patterns & Trends: click one to open it
const recurringAlerts = [
  {
    id: 'r1',
    title: 'Recurring queue buildup',
    details: alertDetailItems,
    detailsTo: '/alerts/3',
  },
  {
    id: 'r2',
    title: 'Low average speed',
    details: [
      { label: 'Location', value: 'East approach' },
      { label: 'When', value: 'Weekdays, 16:00-18:00' },
      { label: 'How often', value: '3 of 5 days' },
      { label: 'Status', value: <Badge variant="warning">Active</Badge> },
    ],
    detailsTo: '/alerts/4',
  },
  {
    id: 'r3',
    title: 'High V/C ratio',
    details: [
      { label: 'Location', value: 'West approach' },
      { label: 'When', value: 'Weekends, 20:00-22:00' },
      { label: 'How often', value: '2 of 2 days' },
      { label: 'Status', value: <Badge variant="success">Resolved</Badge> },
    ],
  },
]

// Example bars for the HistoricalTimeline examples (fake data)

const QUARTER_HOUR = 15 * 60 * 1000 // 15 minutes, in milliseconds

// The time of the newest bar when the page first opens
const TIMELINE_START = new Date('2026-10-10T21:30:00').getTime()

// Builds 96 bars (24 hours, one per 15 minutes) ending at the given time.
// The numbers imitate a normal day: a morning peak, an evening peak and a
// quiet night, with one hour of missing data.
function makeTimelineBars(newestTime) {
  const bars = []

  for (let stepsBack = 95; stepsBack >= 0; stepsBack--) {
    const date = new Date(newestTime - stepsBack * QUARTER_HOUR)
    const time = date.toISOString()
    const hour = date.getHours() + date.getMinutes() / 60

    // Pretend the sensors were down between 03:00 and 04:00
    if (hour >= 3 && hour < 4) {
      bars.push({ time })
      continue
    }

    const morningPeak = 0.7 * Math.exp(-((hour - 7.75) ** 2) / 2.2)
    const eveningPeak = 0.8 * Math.exp(-((hour - 17.5) ** 2) / 4)
    const wobble = 0.04 * Math.sin(hour * 5)
    const value = Math.min(1, 0.12 + morningPeak + eveningPeak + wobble)

    let level = 'low'
    if (value > 0.4) level = 'moderate'
    if (value > 0.7) level = 'high'

    bars.push({ time, value, level })
  }

  return bars
}

// Example values for the PlaybackBar examples (fake data).
// All times are in simulated seconds: 900 seconds = 15 minutes.
const FORECAST_LENGTH = 3600

const forecastStarts = [
  { time: 900, label: '15 min' },
  { time: 1800, label: '30 min' },
  { time: 2700, label: '45 min' },
  { time: 3600, label: '60 min' },
]

const COMPARISON_LENGTH = 600

// Example alerts for the AlertCard examples (fake data), one of each type
const alertCards = [
  {
    id: 'c1',
    type: 'current',
    title: 'Queue spillback',
    details: [
      { label: 'Affected area', value: 'North approach' },
      { label: 'Detected at', value: '14:05' },
      { label: 'Status', value: <Badge variant="warning">Active</Badge> },
    ],
    detailsTo: '/alerts/1',
  },
  {
    id: 'f1',
    type: 'forecast',
    title: 'Queue buildup',
    details: [
      { label: 'Affected area', value: 'South approach' },
      { label: 'Expected in', value: '12 min' },
      { label: 'Horizon', value: '+15 min' },
    ],
    detailsTo: '/alerts/2',
  },
  {
    id: 'p1',
    type: 'pattern',
    title: 'Recurring high V/C',
    details: [
      { label: 'Location', value: 'West approach' },
      { label: 'When', value: 'Weekends, 12:00-15:00' },
      { label: 'How often', value: '2 of 2 days' },
      { label: 'Last seen', value: 'Sat 10 Oct' },
    ],
    // no detailsTo: the card says "No intervention available"
  },
]

// A stand-in for the real simulation, only for the SimulationViewport
// examples: a crossing with rectangles for cars. Every car's position is
// worked out from the time it is given, which is exactly how the real
// drawing will be connected to the PlaybackBar.
function DemoTraffic({ time, cars, speed }) {
  const distance = time * speed // how far every car has travelled

  return (
    <svg viewBox="0 0 400 200" preserveAspectRatio="xMidYMid slice" className="demo-traffic">
      <rect className="demo-road" x="0" y="80" width="400" height="40" />
      <rect className="demo-road" x="180" y="0" width="40" height="200" />

      {Array.from({ length: cars }, (_, index) => {
        const gap = (index * 440) / cars // spread the cars out along the road

        return (
          <g key={index} className="demo-car">
            {/* eastbound, westbound, then southbound */}
            <rect x={((gap + distance) % 440) - 20} y="103" width="12" height="6" rx="2" />
            <rect x={420 - ((gap + 60 + distance) % 440)} y="91" width="12" height="6" rx="2" />
            <rect x="187" y={((gap * 0.55 + distance) % 240) - 20} width="6" height="12" rx="2" />
          </g>
        )
      })}
    </svg>
  )
}

// A page for trying out the shared components. It is not part of the real
// app: it is a reference for the team, showing how each component is used.
function ComponentPreview() {
  // Each Select needs a place to remember what is currently chosen
  const [period, setPeriod] = useState('30')
  const [openApproach, setOpenApproach] = useState('APP_E')
  const [intersection, setIntersection] = useState('')
  const [metric, setMetric] = useState('delay')

  // The same goes for each SegmentedControl
  const [dayType, setDayType] = useState('all')
  const [mapView, setMapView] = useState('segments')
  const [speed, setSpeed] = useState('10')

  // HistoricalTimeline: the selected time (null = latest), and the time of
  // the newest bar, which the "15 minutes pass" button moves forward
  const [timelineTime, setTimelineTime] = useState(null)
  const [timelineNewest, setTimelineNewest] = useState(TIMELINE_START)
  const timelineBars = makeTimelineBars(timelineNewest)

  // PlaybackBar, forecast style: the selected mark is where the forecast
  // starts. It plays from there to the end.
  const [forecastStart, setForecastStart] = useState(900)
  const forecastPlayback = usePlayback({
    start: forecastStart,
    duration: FORECAST_LENGTH,
  })

  function selectForecastStart(time) {
    setForecastStart(time)
    forecastPlayback.playFrom(time)
  }

  // PlaybackBar, comparison style: one clock for two simulations
  const comparisonPlayback = usePlayback({ duration: COMPARISON_LENGTH })

  // SimulationViewport: one clock for the single example, one shared by
  // the before-and-after pair
  const viewportPlayback = usePlayback({ duration: COMPARISON_LENGTH })
  const pairPlayback = usePlayback({ duration: COMPARISON_LENGTH })

  return (
    <>
      <h1>Component preview</h1>

      <section className="preview-section">
        <h2>Button</h2>
        <div className="preview-row">
          <Button>Primary</Button>
          <Button variant="secondary">Secondary</Button>
          <Button size="sm">Small primary</Button>
          <Button variant="secondary" size="sm">
            Latest
          </Button>
          <Button disabled>Disabled</Button>
          <Button onClick={() => alert('Clicked!')}>Click me</Button>
        </div>
      </section>

      <section className="preview-section">
        <h2>BrandMark</h2>
        <div className="preview-row">
          <BrandMark />
          <BrandMark size="md" />
        </div>
        <p className="preview-note">The logo square. Put the word "Jaadah" next to it as text.</p>
      </section>

      <section className="preview-section">
        <h2>Card</h2>
        <div className="preview-row preview-row-top">
          <Card title="Current KPIs" className="preview-card">
            <p>A card with a title. The body can hold anything.</p>
          </Card>

          <Card
            title="Historical Timeline"
            action={
              <Button variant="secondary" size="sm">
                Latest
              </Button>
            }
            className="preview-card"
          >
            <p>A card with a title and an action on the right.</p>
          </Card>

          <Card className="preview-card">
            <p>A card with no title.</p>
          </Card>

          <Card title="Location & General Information" floating className="preview-card">
            <p>A floating card, for panels on top of the map.</p>
          </Card>
        </div>
      </section>

      <section className="preview-section">
        <h2>Badge</h2>
        <div className="preview-row">
          <Badge variant="count">3</Badge>
          <Badge variant="count">12</Badge>
          <Badge>Neutral</Badge>
          <Badge variant="success">Resolved</Badge>
          <Badge variant="warning">Active</Badge>
          <Badge variant="danger">Severe</Badge>
        </div>

        <div className="preview-row preview-row-top">
          <Card
            title="Active Alerts"
            action={<Badge variant="count">3</Badge>}
            className="preview-card"
          >
            <p>A count badge in a card header, as on the alert panels.</p>
          </Card>
        </div>
      </section>

      <section className="preview-section">
        <h2>EmptyState</h2>
        <div className="preview-row preview-row-top">
          <EmptyState className="preview-card">
            No alerts are currently available.
          </EmptyState>

          <EmptyState title="No performance data available" className="preview-card">
            Try a different time period or day type.
          </EmptyState>

          <EmptyState variant="error" title="Simulation did not run" className="preview-card">
            The baseline simulation is unavailable.
          </EmptyState>
        </div>
      </section>

      <section className="preview-section">
        <h2>Select</h2>
        <div className="preview-row">
          <Select
            label="Time period"
            options={periodOptions}
            value={period}
            onChange={setPeriod}
          />

          <Select
            ariaLabel="Intersection"
            placeholder="Select intersection"
            options={intersectionOptions}
            value={intersection}
            onChange={setIntersection}
          />

          <Select
            ariaLabel="Chart metric"
            size="sm"
            options={metricOptions}
            value={metric}
            onChange={setMetric}
          />
        </div>

        <p className="preview-note">
          Selected values: period = {period}, intersection ={' '}
          {intersection || '(none)'}, metric = {metric}
        </p>
      </section>

      <section className="preview-section">
        <h2>SegmentedControl</h2>
        <div className="preview-row">
          <SegmentedControl
            label="Day type"
            options={dayTypeOptions}
            value={dayType}
            onChange={setDayType}
          />

          <SegmentedControl
            ariaLabel="Map view"
            size="sm"
            options={mapViewOptions}
            value={mapView}
            onChange={setMapView}
          />

          <SegmentedControl
            label="Acceleration rate"
            size="sm"
            options={speedOptions}
            value={speed}
            onChange={setSpeed}
          />
        </div>

        <p className="preview-note">
          Selected values: dayType = {dayType}, mapView = {mapView}, speed ={' '}
          {speed}
        </p>

        {/* A Select and a SegmentedControl in one row, as on Patterns & Trends */}
        <div className="preview-row">
          <Select
            label="Time period"
            options={periodOptions}
            value={period}
            onChange={setPeriod}
          />
          <SegmentedControl
            label="Day type"
            options={dayTypeOptions}
            value={dayType}
            onChange={setDayType}
          />
          <Button
            variant="secondary"
            onClick={() => {
              setPeriod('30')
              setDayType('all')
            }}
          >
            Reset
          </Button>
        </div>
      </section>

      <section className="preview-section">
        <h2>KpiTile</h2>

        {/* Inline layout inside a card, as on Current Traffic */}
        <div className="preview-row preview-row-top">
          <Card title="Current KPIs" className="preview-card-wide">
            <div className="preview-kpi-grid">
              <KpiTile label="Control Delay" value={46} unit="s" change={4} changeTone="bad" />
              <KpiTile label="Queue Length" value={128} unit="m" change={12} changeTone="bad" />
              <KpiTile label="Avg Speed" value={24} unit="km/h" change={-6} changeTone="bad" />
              <KpiTile label="Throughput" value={1842} unit="veh/h" change={3} changeTone="good" />
              <KpiTile label="V/C Ratio" value={0.91} change={0.04} changeUnit="" changeTone="bad" />
              <KpiTile label="Level of Service" />
            </div>
          </Card>
        </div>

        {/* Stacked layout, as on Patterns & Trends */}
        <div className="preview-row preview-row-top">
          <KpiTile
            layout="stacked"
            label="Avg Control Delay"
            value={46}
            unit="s"
            change={-5}
            changeNote="vs previous"
            changeTone="good"
            className="preview-tile"
          />
          <KpiTile
            layout="stacked"
            label="Avg Speed"
            value={24}
            unit="km/h"
            change={-5}
            changeNote="vs previous"
            changeTone="bad"
            className="preview-tile"
          />
          <KpiTile
            layout="stacked"
            label="Peak Congestion Hour"
            value="07:45"
            className="preview-tile"
          />
        </div>
      </section>

      <section className="preview-section">
        <h2>KpiTile from backend results</h2>

        {/* Stacked tiles in a row line up: the change line sits at the bottom */}
        <div className="kpi-row preview-kpi-row">
          <KpiTile
            layout="stacked"
            label="Avg control delay"
            detail="LOS C · simulation-based"
            {...kpiTileProps(exampleResults.delay.current, exampleResults.delay.previous, 'vs prev. 30 days')}
          />
          <KpiTile
            layout="stacked"
            label="Avg throughput"
            detail="All signalized movements"
            {...kpiTileProps(exampleResults.throughput.current, exampleResults.throughput.previous, 'vs prev. 30 days')}
          />
          <KpiTile
            layout="stacked"
            label="Critical v/c, peak 15 min"
            detail="Weekdays 17:15–17:30"
            {...kpiTileProps(exampleResults.vc.current, exampleResults.vc.previous, 'vs prev. 30 days')}
          />
          <KpiTile
            layout="stacked"
            label="Peak congestion window"
            value="17:15"
            unit="–17:30"
            detail="Highest avg control delay, weekdays"
            changeNote="Same window as prev. 30 days"
            tag="Simulated"
          />
          <KpiTile
            layout="stacked"
            label="Storage ratio"
            {...kpiTileProps(exampleResults.storage.current)}
          />
          <KpiTile
            layout="stacked"
            label="LOS, right slip lane"
            {...kpiTileProps(exampleResults.losRight.current)}
          />
        </div>
      </section>

      <section className="preview-section">
        <h2>Notice</h2>
        <div className="preview-stack">
          <Notice variant="warning">
            Sample data for layout only: all values on this page are illustrative.
          </Notice>
          <Notice>Results cover weekdays only.</Notice>
        </div>
      </section>

      <section className="preview-section">
        <h2>LosBadge</h2>
        <div className="preview-row">
          {GRADES.map((grade) => (
            <LosBadge key={grade} grade={grade} />
          ))}
          <LosBadge />
        </div>
      </section>

      <section className="preview-section">
        <h2>MethodTag</h2>
        <p className="preview-row">
          Highest v/c <MethodTag method="hcm" />
        </p>
        <p className="preview-note">
          After a KPI calculated with the HCM method. Hover or focus it to read what that means.
          Simulated values get no tag.
        </p>
      </section>

      <section className="preview-section">
        <h2>InfoList</h2>
        <div className="preview-row preview-row-top">
          <Card title="Location & General Information" className="preview-card">
            <InfoList items={locationItems} />
          </Card>

          <Card title="A value can be a component" className="preview-card">
            <InfoList items={alertDetailItems} />
          </Card>

          <Card title="A missing value" className="preview-card">
            <InfoList items={incompleteItems} />
          </Card>
        </div>
      </section>

      <section className="preview-section">
        <h2>LocationInfoCard</h2>
        <div className="preview-row preview-row-top">
          {/* All data present, floating as it would be on the map */}
          <LocationInfoCard
            intersection={fullIntersection}
            floating
            className="preview-card"
          />

          {/* Some fields missing */}
          <LocationInfoCard
            intersection={partialIntersection}
            className="preview-card"
          />

          {/* No intersection at all, e.g. while the data is still loading */}
          <LocationInfoCard className="preview-card" />
        </div>
      </section>

      <section className="preview-section">
        <h2>LocationSummary</h2>
        <div className="preview-row preview-row-top">
          {/* Click or hover the name to open the full card */}
          <LocationSummary intersection={fullIntersection} />
        </div>
      </section>

      <section className="preview-section">
        <h2>ApproachPanel</h2>
        <div className="preview-row preview-row-top">
          {/* Click a chip to open or close its approach */}
          <ApproachPanel
            approaches={exampleApproaches}
            openId={openApproach}
            onToggle={(id) => setOpenApproach((open) => (open === id ? null : id))}
          />
        </div>
      </section>

      <section className="preview-section">
        <h2>AlertList</h2>
        <div className="preview-row preview-row-top">
          <AlertList
            title="Active Alerts"
            alerts={activeAlerts}
            className="preview-card-wide"
          />

          <AlertList
            title="Recurring Problem Alerts"
            alerts={recurringAlerts}
            className="preview-card-wide"
          />

          <AlertList
            title="Forecast Alerts"
            alerts={[]}
            emptyMessage="No upcoming traffic problems are currently predicted."
            className="preview-card-wide"
          />

          <AlertList
            title="Active Alerts"
            error="Abnormal traffic detection is not responding."
            className="preview-card-wide"
          />
        </div>
      </section>

      <section className="preview-section">
        <h2>PageHeader</h2>

        {/* As on Alerts: a plain subtitle and several buttons */}
        <div className="preview-box">
          <PageHeader
            title="Alerts"
            subtitle="Selected area: Intersection A"
            actions={
              <>
                <Button variant="secondary" size="sm">Current 3</Button>
                <Button variant="secondary" size="sm">Forecast 3</Button>
                <Button variant="secondary" size="sm">Patterns 3</Button>
              </>
            }
          />
        </div>

        {/* As on Alert Details: Breadcrumbs above, a subtitle and one button */}
        <div className="preview-box">
          <Breadcrumbs items={[{ label: 'Alerts', to: '/alerts' }, { label: 'Queue spillback' }]} />
          <PageHeader
            title="Queue spillback on the north approach"
            subtitle="Prince Turki Al-Awwal Rd × Imam Saud Rd"
            actions={<Button variant="secondary">View interventions (4)</Button>}
          />
        </div>

        {/* Title only */}
        <div className="preview-box">
          <PageHeader title="Traffic Patterns & Trends" />
        </div>
      </section>

      <section className="preview-section">
        <h2>Breadcrumbs</h2>
        <div className="preview-stack">
          <Breadcrumbs items={[{ label: 'Alerts', to: '/alerts' }, { label: 'Queue spillback' }]} />
          <Breadcrumbs
            items={[
              { label: 'Alerts', to: '/alerts' },
              { label: 'Queue spillback', to: '/alerts/1' },
              { label: 'Extend the north left-turn green' },
            ]}
          />
        </div>
        <p className="preview-note">The last item is the current page, so it has no link.</p>
      </section>

      <section className="preview-section">
        <h2>AlertCard</h2>
        <div className="preview-grid-3">
          {alertCards.map((alert) => (
            <AlertCard
              key={alert.id}
              type={alert.type}
              title={alert.title}
              details={alert.details}
              detailsTo={alert.detailsTo}
            />
          ))}
        </div>
      </section>

      <section className="preview-section">
        <h2>HistoricalTimeline</h2>
        <div className="preview-row">
          <HistoricalTimeline
            bars={timelineBars}
            value={timelineTime}
            onChange={setTimelineTime}
            className="preview-full"
          />
        </div>

        {/* Imitates real time: drops the oldest bar and adds a new one */}
        <div className="preview-row">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setTimelineNewest(timelineNewest + QUARTER_HOUR)}
          >
            15 minutes pass
          </Button>
          <span className="preview-value">
            value = {timelineTime ?? 'null (latest)'}
          </span>
        </div>

        <div className="preview-row preview-row-top">
          <HistoricalTimeline bars={[]} className="preview-card-wide" />

          <HistoricalTimeline
            error="Historical traffic data could not be loaded."
            className="preview-card-wide"
          />
        </div>
      </section>

      <section className="preview-section">
        <h2>PlaybackBar</h2>

        {/* With start marks and a speed control, as on Traffic Forecast */}
        <div className="preview-row">
          <Card className="preview-full">
            <PlaybackBar
              duration={FORECAST_LENGTH}
              time={forecastPlayback.time}
              onTimeChange={forecastPlayback.setTime}
              playing={forecastPlayback.playing}
              onPlayingChange={forecastPlayback.setPlaying}
              speed={forecastPlayback.speed}
              onSpeedChange={forecastPlayback.setSpeed}
              marks={forecastStarts}
              selectedMark={forecastStart}
              onMarkSelect={selectForecastStart}
            />
          </Card>
        </div>

        <p className="preview-note">
          time = {Math.floor(forecastPlayback.time)} s, start = {forecastStart} s, speed = x
          {forecastPlayback.speed}, playing = {String(forecastPlayback.playing)}
        </p>

        {/* Without marks, as on Recommendation Details */}
        <div className="preview-row">
          <Card className="preview-full">
            <PlaybackBar
              duration={COMPARISON_LENGTH}
              time={comparisonPlayback.time}
              onTimeChange={comparisonPlayback.setTime}
              playing={comparisonPlayback.playing}
              onPlayingChange={comparisonPlayback.setPlaying}
              speed={comparisonPlayback.speed}
              onSpeedChange={comparisonPlayback.setSpeed}
            />
          </Card>
        </div>

        {/* Switched off, for when the simulation did not run */}
        <div className="preview-row">
          <Card className="preview-full">
            <PlaybackBar
              duration={COMPARISON_LENGTH}
              time={0}
              playing={false}
              speed={10}
              disabled
            />
          </Card>
        </div>
      </section>

      <section className="preview-section">
        <h2>SimulationViewport</h2>

        {/* The empty frame with a floating card and the time, as on
            Current Traffic before the simulation is connected */}
        <div className="preview-row">
          <SimulationViewport
            overlay={<LocationInfoCard intersection={fullIntersection} floating />}
            timeLabel="Sat 10 Oct, 21:30"
            mode="live"
            height={300}
            className="preview-full"
          />
        </div>

        {/* Something drawn inside, and a PlaybackBar in the bottom strip,
            as on Traffic Forecast */}
        <div className="preview-row">
          <SimulationViewport
            timeLabel={`+${Math.floor(viewportPlayback.time / 60)} min`}
            mode="forecast"
            height={240}
            className="preview-full"
            footer={
              <PlaybackBar
                duration={COMPARISON_LENGTH}
                time={viewportPlayback.time}
                onTimeChange={viewportPlayback.setTime}
                playing={viewportPlayback.playing}
                onPlayingChange={viewportPlayback.setPlaying}
                speed={viewportPlayback.speed}
                onSpeedChange={viewportPlayback.setSpeed}
              />
            }
          >
            <DemoTraffic time={viewportPlayback.time} cars={7} speed={2} />
          </SimulationViewport>
        </div>

        {/* Two viewports reading one clock, as on Recommendation Details */}
        <div className="preview-row preview-row-top">
          <SimulationViewport title="Baseline" height={200} className="preview-half">
            <DemoTraffic time={pairPlayback.time} cars={10} speed={1.2} />
          </SimulationViewport>

          <SimulationViewport title="Intervention" height={200} className="preview-half">
            <DemoTraffic time={pairPlayback.time} cars={6} speed={2.4} />
          </SimulationViewport>
        </div>

        <div className="preview-row">
          <Card className="preview-full">
            <PlaybackBar
              duration={COMPARISON_LENGTH}
              time={pairPlayback.time}
              onTimeChange={pairPlayback.setTime}
              playing={pairPlayback.playing}
              onPlayingChange={pairPlayback.setPlaying}
              speed={pairPlayback.speed}
              onSpeedChange={pairPlayback.setSpeed}
            />
          </Card>
        </div>

        {/* The simulation did not run */}
        <div className="preview-row preview-row-top">
          <SimulationViewport
            title="Baseline"
            height={200}
            error="The baseline simulation is unavailable."
            className="preview-half"
          />

          <SimulationViewport
            title="Intervention"
            height={200}
            error="The intervention simulation is unavailable."
            className="preview-half"
          />
        </div>
      </section>
    </>
  )
}

export default ComponentPreview