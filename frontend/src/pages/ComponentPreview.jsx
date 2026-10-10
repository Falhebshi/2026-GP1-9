import { useState } from 'react'
import AlertList from '../components/AlertList'
import Badge from '../components/Badge'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
import InfoList from '../components/InfoList'
import KpiTile from '../components/KpiTile'
import LocationInfoCard from '../components/LocationInfoCard'
import SegmentedControl from '../components/SegmentedControl'
import Select from '../components/Select'
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
    interventionsTo: '/recommendations',
  },
  {
    id: 'a2',
    title: 'Low average speed',
    subtitle: 'East approach · 7 min ago',
    interventionsTo: '/recommendations',
  },
  {
    id: 'a3',
    title: 'High V/C ratio',
    subtitle: 'West approach · 11 min ago',
    // no interventionsTo: this alert shows no link
  },
]

// Alerts with details, as on Patterns & Trends: click one to open it
const recurringAlerts = [
  {
    id: 'r1',
    title: 'Recurring queue buildup',
    details: alertDetailItems,
    interventionsTo: '/recommendations',
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
    interventionsTo: '/recommendations',
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

// A page for trying out the shared components. It is not part of the real
// app: it is a reference for the team, showing how each component is used.
function ComponentPreview() {
  // Each Select needs a place to remember what is currently chosen
  const [period, setPeriod] = useState('30')
  const [intersection, setIntersection] = useState('')
  const [metric, setMetric] = useState('delay')

  // The same goes for each SegmentedControl
  const [dayType, setDayType] = useState('all')
  const [mapView, setMapView] = useState('segments')
  const [speed, setSpeed] = useState('10')

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
    </>
  )
}

export default ComponentPreview