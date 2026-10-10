import { useState } from 'react'
import Badge from '../components/Badge'
import Button from '../components/Button'
import Card from '../components/Card'
import EmptyState from '../components/EmptyState'
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
    </>
  )
}

export default ComponentPreview