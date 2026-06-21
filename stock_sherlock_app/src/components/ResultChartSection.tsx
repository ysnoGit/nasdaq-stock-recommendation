import { BarChart3 } from 'lucide-react'
import {
  CartesianGrid,
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { EvaluationStatus, ResultChartPoint } from '../types/screening'

interface ResultChartSectionProps {
  data: ResultChartPoint[]
  errorMessage: string | null
  hasRun: boolean
  isLoading: boolean
  useQuarterAxis: boolean
  selectedDate: string | null
  onSelectDate: (date: string) => void
}

interface ChartDotProps {
  cx?: number
  cy?: number
  payload?: PendingChartPoint
}

interface PendingChartPoint extends ResultChartPoint {
  pendingMarker: number | null
}

const STATUS_LABELS: Record<Exclude<EvaluationStatus, 'complete'>, string> = {
  pending_f: 'Awaiting next trading session',
  pending_h: 'Awaiting following completed week',
  no_market_session: 'No market session',
  no_data: 'No fundamental records',
}

function formatAxisDate(date: string): string {
  const [, month, day] = date.split('-')
  return `${month}/${day}`
}

function formatFullDate(date: string): string {
  return new Intl.DateTimeFormat('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(`${date}T12:00:00`))
}

function formatQuarter(date: string): string {
  const parsed = new Date(`${date}T12:00:00`)
  return `${parsed.getFullYear()} Q${Math.floor(parsed.getMonth() / 3) + 1}`
}

export function ResultChartSection({
  data,
  errorMessage,
  hasRun,
  isLoading,
  useQuarterAxis,
  selectedDate,
  onSelectDate,
}: ResultChartSectionProps) {
  const chartWidth = Math.max(760, data.length * 72)
  const completedCounts = data.flatMap((point) =>
    point.selectedCompanyCount === null ? [] : [point.selectedCompanyCount],
  )
  const maximumCount = Math.max(0, ...completedCounts)
  const yAxisMaximum = Math.max(5, Math.ceil((maximumCount + 2) / 5) * 5)
  const chartData: PendingChartPoint[] = data.map((point) => ({
    ...point,
    pendingMarker: point.evaluationStatus === 'pending_f'
      || point.evaluationStatus === 'pending_h'
      || point.evaluationStatus === 'no_market_session'
      ? yAxisMaximum
      : null,
  }))

  const renderCountDot = ({ cx, cy, payload }: ChartDotProps) => {
    if (
      cx === undefined ||
      cy === undefined ||
      !payload ||
      payload.selectedCompanyCount === null
    ) return <g />

    const isSelected = payload.date === selectedDate
    const selectDate = () => onSelectDate(payload.date)
    const isNoData = payload.evaluationStatus === 'no_data'
    return (
      <circle
        aria-label={`${useQuarterAxis ? formatQuarter(payload.date) : formatFullDate(payload.date)}: ${isNoData ? 'no fundamental records' : `${payload.selectedCompanyCount} selected companies`}`}
        className={`chart-point${isNoData ? ' chart-point-no-data' : ''}`}
        cx={cx}
        cy={cy}
        fill={isSelected ? (isNoData ? '#dce1e6' : '#0b6b57') : '#ffffff'}
        onClick={selectDate}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') selectDate()
        }}
        r={isSelected ? 6 : 4.5}
        role="button"
        stroke={isNoData ? '#7a858f' : '#0b6b57'}
        strokeDasharray={isNoData ? '3 2' : undefined}
        strokeWidth={2}
        tabIndex={0}
      />
    )
  }

  const renderPendingDot = ({ cx, cy, payload }: ChartDotProps) => {
    if (
      cx === undefined ||
      cy === undefined ||
      !payload ||
      payload.evaluationStatus === 'complete'
    ) return <g />

    const isSelected = payload.date === selectedDate
    const label = STATUS_LABELS[payload.evaluationStatus]
    return (
      <circle
        aria-label={`${formatFullDate(payload.date)}: ${label}`}
        className="chart-point chart-point-pending"
        cx={cx}
        cy={cy}
        fill={isSelected ? '#dce1e6' : '#ffffff'}
        onClick={() => onSelectDate(payload.date)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') onSelectDate(payload.date)
        }}
        r={isSelected ? 6 : 5}
        role="button"
        stroke="#7a858f"
        strokeDasharray="3 2"
        strokeWidth={2}
        tabIndex={0}
      />
    )
  }

  return (
    <section className="result-section" aria-labelledby="result-chart-title">
      <div className="result-section-heading">
        <div>
          <span className="result-section-icon" aria-hidden="true">
            <BarChart3 size={19} />
          </span>
          <h2 id="result-chart-title">Selected Company Count</h2>
        </div>
        {hasRun && data.length > 0 && (
          <span>{data.length} result {useQuarterAxis ? 'quarters' : 'dates'}</span>
        )}
      </div>

      {isLoading ? (
        <div className="result-empty-state">
          <BarChart3 aria-hidden="true" size={27} strokeWidth={1.6} />
          <p>Evaluating screening conditions…</p>
        </div>
      ) : errorMessage ? (
        <div className="result-empty-state result-error-state" role="alert">
          <p>{errorMessage}</p>
        </div>
      ) : !hasRun ? (
        <div className="result-empty-state">
          <BarChart3 aria-hidden="true" size={27} strokeWidth={1.6} />
          <p>Run Filter to view results</p>
        </div>
      ) : data.length === 0 ? (
        <div className="result-empty-state">
          <BarChart3 aria-hidden="true" size={27} strokeWidth={1.6} />
          <p>No result dates available</p>
        </div>
      ) : (
        <div className="chart-scroll-container" data-testid="chart-scroll-container">
          <LineChart
            data={chartData}
            height={340}
            margin={{ top: 22, right: 30, bottom: 22, left: 4 }}
            width={chartWidth}
          >
            <CartesianGrid stroke="#e4e8ec" strokeDasharray="4 4" vertical={false} />
            <XAxis
              axisLine={{ stroke: '#c9d0d8' }}
              dataKey="date"
              interval={0}
              minTickGap={12}
              tick={{ fill: '#66717d', fontSize: 11 }}
              tickFormatter={useQuarterAxis ? formatQuarter : formatAxisDate}
              tickLine={false}
            />
            <YAxis
              allowDecimals={false}
              axisLine={false}
              domain={[0, yAxisMaximum]}
              tick={{ fill: '#66717d', fontSize: 11 }}
              tickLine={false}
              width={36}
            />
            <Tooltip
              cursor={{ stroke: '#aeb8c2', strokeDasharray: '4 4' }}
              formatter={(value, name, item) => {
                const point = item.payload as PendingChartPoint
                if (point.evaluationStatus === 'no_data') {
                  return [STATUS_LABELS.no_data, 'Status']
                }
                if (name === 'pendingMarker' && point.evaluationStatus !== 'complete') {
                  return [STATUS_LABELS[point.evaluationStatus], 'Status']
                }
                return [Number(value), 'Selected companies']
              }}
              labelFormatter={(label) => useQuarterAxis
                ? formatQuarter(String(label))
                : formatFullDate(String(label))}
            />
            <Line
              activeDot={false}
              connectNulls={false}
              dataKey="selectedCompanyCount"
              dot={renderCountDot}
              isAnimationActive={false}
              stroke="#0b6b57"
              strokeWidth={2.5}
              type="monotone"
            />
            <Line
              activeDot={false}
              connectNulls={false}
              dataKey="pendingMarker"
              dot={renderPendingDot}
              isAnimationActive={false}
              legendType="none"
              stroke="transparent"
              type="linear"
            />
          </LineChart>
          {data.some((point) => ['pending_f', 'pending_h', 'no_market_session'].includes(point.evaluationStatus)) && (
            <p className="chart-pending-note">
              Hollow markers await F or H confirmation and do not represent zero.
            </p>
          )}
        </div>
      )}
    </section>
  )
}
