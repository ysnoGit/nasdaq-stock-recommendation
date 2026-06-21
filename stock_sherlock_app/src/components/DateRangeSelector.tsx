import { CalendarDays } from 'lucide-react'
import type { DateRange } from '../types/screening'

interface DateRangeSelectorProps {
  dateRange: DateRange
  disabled: boolean
  inclusiveDayCount: number | null
  maximumDate: string
  minimumDate?: string
  validationMessage: string | null
  onChange: (field: keyof DateRange, value: string) => void
}

export function DateRangeSelector({
  dateRange,
  disabled,
  inclusiveDayCount,
  maximumDate,
  minimumDate,
  validationMessage,
  onChange,
}: DateRangeSelectorProps) {
  return (
    <div className={`date-range-block${disabled ? ' date-range-block-disabled' : ''}`}>
      <div className="parameter-group-heading">
        <span className="parameter-group-icon" aria-hidden="true">
          <CalendarDays size={17} />
        </span>
        <div>
          <h3>Inspection window</h3>
          <p>Inclusive calendar dates</p>
        </div>
      </div>

      <div className="date-fields">
        <label className="field-control">
          <span>Start date</span>
          <input
            disabled={disabled}
            max={maximumDate}
            min={minimumDate}
            type="date"
            value={dateRange.startDate}
            onChange={(event) => onChange('startDate', event.target.value)}
          />
        </label>
        <label className="field-control">
          <span>End date</span>
          <input
            disabled={disabled}
            max={maximumDate}
            min={minimumDate}
            type="date"
            value={dateRange.endDate}
            onChange={(event) => onChange('endDate', event.target.value)}
          />
        </label>
      </div>

      <div className="date-range-status" aria-live="polite">
        {disabled ? (
          <span>—</span>
        ) : validationMessage ? (
          <span className="validation-message">{validationMessage}</span>
        ) : (
          <span>
            {inclusiveDayCount ?? 0} {inclusiveDayCount === 1 ? 'day' : 'days'}
          </span>
        )}
      </div>
    </div>
  )
}
