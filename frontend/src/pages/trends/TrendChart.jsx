import { useState } from 'react'
import Card from '../../components/Card'
import EmptyState from '../../components/EmptyState'
import Select from '../../components/Select'
import useElementWidth from '../../hooks/useElementWidth'
import { displayUnit, formatKpiValue, hasValue, KPI_DEFINITIONS } from '../../utils/kpi'
import { dayAndDate, shortDate } from '../../utils/format'
import { compactNumber, niceScale } from './chartScale'
import './TrendChart.css'

// The menu above the chart
const METRIC_LABELS = {
  control_delay: 'Daily avg control delay',
  queue_length: 'Daily 95th-pct queue',
  throughput: 'Daily avg throughput',
  volume_to_capacity_ratio: 'Daily peak v/c',
}

const HEIGHT = 230
const MARGIN = { top: 18, right: 72, bottom: 26, left: 40 }

// Performance trend: one value per day for the chosen KPI, with the LOS
// threshold lines and anomaly days marked. Hover (or use the arrow keys)
// to read any day.
//
//   trend   data.trend from the trends service:
//           { metrics, series, referenceLines, anomalies }
function TrendChart({ trend }) {
  const [metric, setMetric] = useState(trend.metrics[0])
  const [hoverIndex, setHoverIndex] = useState(null)
  const [ref, width] = useElementWidth()

  const points = trend.series[metric] ?? []
  const references = trend.referenceLines?.[metric] ?? []
  const anomalyDates = new Set((trend.anomalies ?? []).map((a) => a.date))
  const unit = displayUnit(points.find((p) => hasValue(p.result))?.result.unit)

  const options = trend.metrics.map((m) => ({
    value: m,
    label: `${METRIC_LABELS[m] ?? KPI_DEFINITIONS[m]?.label ?? m}${unitLabel(trend, m)}`,
  }))

  const menu = (
    <Select
      ariaLabel="KPI shown in the chart"
      size="sm"
      options={options}
      value={metric}
      onChange={(value) => {
        setMetric(value)
        setHoverIndex(null)
      }}
    />
  )

  if (!points.some((p) => hasValue(p.result))) {
    return (
      <Card title="Performance trend" action={menu}>
        <EmptyState>No values for this KPI in the selected period.</EmptyState>
      </Card>
    )
  }

  // ---- Scales: turn a day number and a value into pixels -----------------
  const plotWidth = Math.max(width - MARGIN.left - MARGIN.right, 10)
  const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
  const values = points.filter((p) => hasValue(p.result)).map((p) => p.result.value)
  const { max, ticks } = niceScale(Math.max(...values, ...references.map((r) => r.value)) * 1.08)

  const x = (index) =>
    MARGIN.left + (points.length === 1 ? plotWidth / 2 : (index / (points.length - 1)) * plotWidth)
  const y = (value) => MARGIN.top + plotHeight - (value / max) * plotHeight

  // The line, broken wherever a day has no value (never drawn as zero)
  const segments = []
  let current = []
  points.forEach((p, i) => {
    if (hasValue(p.result)) {
      current.push(`${x(i).toFixed(1)},${y(p.result.value).toFixed(1)}`)
    } else if (current.length) {
      segments.push(current)
      current = []
    }
  })
  if (current.length) segments.push(current)

  // About five date labels along the bottom
  const labelEvery = Math.max(1, Math.ceil(points.length / 5))
  const lastIndex = points.length - 1
  const lastValueIndex = points.map((p) => hasValue(p.result)).lastIndexOf(true)

  // Hovering: find the day nearest the pointer
  function handlePointer(event) {
    const box = event.currentTarget.getBoundingClientRect()
    const px = event.clientX - box.left
    const ratio = (px - MARGIN.left) / plotWidth
    const index = Math.round(ratio * lastIndex)
    setHoverIndex(Math.min(Math.max(index, 0), lastIndex))
  }

  // Arrow keys move through the days, for people using the keyboard
  function handleKey(event) {
    if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') {
      event.preventDefault()
      const step = event.key === 'ArrowRight' ? 1 : -1
      setHoverIndex((i) => Math.min(Math.max((i ?? (step > 0 ? -1 : lastIndex + 1)) + step, 0), lastIndex))
    }
    if (event.key === 'Escape') setHoverIndex(null)
  }

  const hovered = hoverIndex === null ? null : points[hoverIndex]

  return (
    <Card title="Performance trend" action={menu}>
      <div
        ref={ref}
        className="trend-chart"
        tabIndex={0}
        role="img"
        aria-label={`${METRIC_LABELS[metric]} over ${points.length} days. Use the arrow keys to read each day.`}
        onPointerMove={handlePointer}
        onPointerLeave={() => setHoverIndex(null)}
        onKeyDown={handleKey}
        onBlur={() => setHoverIndex(null)}
      >
        {width > 0 && (
          <svg width={width} height={HEIGHT} aria-hidden="true">
            {/* Grid lines and value labels on the left */}
            {ticks.map((tick) => (
              <g key={tick}>
                <line className="trend-grid" x1={MARGIN.left} x2={MARGIN.left + plotWidth} y1={y(tick)} y2={y(tick)} />
                <text className="trend-axis" x={MARGIN.left - 8} y={y(tick)} dy="0.32em" textAnchor="end">
                  {compactNumber(tick)}
                </text>
              </g>
            ))}

            {/* Threshold lines, labelled on the right */}
            {references.map((r) => (
              <g key={r.label}>
                <line className="trend-reference" x1={MARGIN.left} x2={MARGIN.left + plotWidth} y1={y(r.value)} y2={y(r.value)} />
                <text className="trend-reference-label" x={MARGIN.left + plotWidth + 6} y={y(r.value)} dy="0.32em">
                  {r.label} {compactNumber(r.value)}
                  {unit && ` ${unit === 's/veh' ? 's' : unit}`}
                </text>
              </g>
            ))}

            {/* Date labels along the bottom */}
            {points.map((p, i) =>
              i % labelEvery === 0 || i === lastIndex ? (
                (i === lastIndex || lastIndex - i >= labelEvery / 2) && (
                  <text
                    key={p.date}
                    className="trend-axis"
                    x={x(i)}
                    y={HEIGHT - 6}
                    textAnchor={i === 0 ? 'start' : i === lastIndex ? 'end' : 'middle'}
                  >
                    {shortDate(p.date)}
                  </text>
                )
              ) : null,
            )}

            {/* Days without a value: a light band, so the gap reads as missing */}
            {points.map((p, i) =>
              hasValue(p.result) ? null : (
                <rect
                  key={`gap-${p.date}`}
                  className="trend-missing"
                  x={x(i) - plotWidth / Math.max(lastIndex, 1) / 2}
                  y={MARGIN.top}
                  width={plotWidth / Math.max(lastIndex, 1)}
                  height={plotHeight}
                />
              ),
            )}

            {/* The line itself */}
            {segments.map((segment, i) =>
              segment.length === 1 ? (
                <circle key={i} className="trend-dot" cx={segment[0].split(',')[0]} cy={segment[0].split(',')[1]} r="3" />
              ) : (
                <polyline key={i} className="trend-line" points={segment.join(' ')} />
              ),
            )}

            {/* Anomaly days: a ring and a short label */}
            {points.map((p, i) =>
              anomalyDates.has(p.date) && hasValue(p.result) ? (
                <g key={`anomaly-${p.date}`}>
                  <circle className="trend-anomaly" cx={x(i)} cy={y(p.result.value)} r="6" />
                  <text className="trend-anomaly-label" x={x(i)} y={y(p.result.value) - 12} textAnchor="middle">
                    {trend.anomalies.find((a) => a.date === p.date)?.label}
                  </text>
                </g>
              ) : null,
            )}

            {/* The latest value: a dot and its number */}
            {lastValueIndex >= 0 && (
              <circle className="trend-end" cx={x(lastValueIndex)} cy={y(points[lastValueIndex].result.value)} r="4" />
            )}

            {/* Hover: a vertical line and a dot on the chosen day */}
            {hovered && (
              <g>
                <line className="trend-crosshair" x1={x(hoverIndex)} x2={x(hoverIndex)} y1={MARGIN.top} y2={MARGIN.top + plotHeight} />
                {hasValue(hovered.result) && (
                  <circle className="trend-end" cx={x(hoverIndex)} cy={y(hovered.result.value)} r="5" />
                )}
              </g>
            )}
          </svg>
        )}

        {hovered && (
          <div
            className="trend-tooltip"
            style={{
              left: `${x(hoverIndex)}px`,
              transform: `translateX(${hoverIndex > lastIndex * 0.6 ? 'calc(-100% - 12px)' : '12px'})`,
            }}
          >
            {hasValue(hovered.result) ? (
              <strong>
                {formatKpiValue(hovered.result)}
                {unit && ` ${unit}`}
              </strong>
            ) : (
              <strong className="trend-tooltip-missing">Unavailable</strong>
            )}
            <span>{dayAndDate(hovered.date)}</span>
            {!hasValue(hovered.result) && hovered.result.reason && (
              <span className="trend-tooltip-reason">{hovered.result.reason}</span>
            )}
            {anomalyDates.has(hovered.date) && <span className="trend-tooltip-flag">Anomaly day</span>}
          </div>
        )}
      </div>
    </Card>
  )
}

// " (s/veh)" for the menu, taken from the data itself
function unitLabel(trend, metric) {
  const unit = displayUnit(trend.series[metric]?.find((p) => hasValue(p.result))?.result.unit)
  return unit ? ` (${unit})` : ''
}

export default TrendChart