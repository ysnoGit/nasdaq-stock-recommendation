import { CalendarRange } from 'lucide-react'
import {
  CALENDAR_QUARTER_OPTIONS,
  FUNDAMENTAL_INSPECTION_PERIOD_OPTIONS,
} from '../config/screeningOptions'
import type {
  ConditionCategory,
  FundamentalInspection,
} from '../types/screening'

interface FundamentalInspectionWindowProps {
  inspection: FundamentalInspection
  selectedConditions: Set<ConditionCategory>
  validationMessage: string | null
  onChange: (field: keyof FundamentalInspection, value: string) => void
}

export function FundamentalInspectionWindow({
  inspection,
  selectedConditions,
  validationMessage,
  onChange,
}: FundamentalInspectionWindowProps) {
  const isAnnual = selectedConditions.has('annualFundamental')
  const isQuarterly = selectedConditions.has('quarterlyFundamental')
  const isEnabled = isAnnual || isQuarterly
  const periodsField = isAnnual
    ? 'annualInspectionPeriods'
    : 'quarterlyInspectionPeriods'

  return (
    <div className={`date-range-block fundamental-window${isEnabled ? '' : ' parameter-block-disabled'}`}>
      <div className="parameter-group-heading">
        <span className="parameter-group-icon" aria-hidden="true">
          <CalendarRange size={17} />
        </span>
        <div>
          <h3>Fundamental inspection</h3>
          <p>Calendar-quarter result window</p>
        </div>
      </div>

      <div className="fundamental-window-fields">
        <label className="field-control">
          <span>Inspection through year</span>
          <input
            disabled={!isEnabled}
            inputMode="numeric"
            max="2100"
            min="1900"
            type="number"
            value={inspection.throughYear}
            onChange={(event) => onChange('throughYear', event.target.value)}
          />
        </label>
        <label className="field-control">
          <span>Quarter</span>
          <select
            disabled={!isEnabled}
            value={inspection.throughQuarter}
            onChange={(event) => onChange('throughQuarter', event.target.value)}
          >
            {CALENDAR_QUARTER_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <label className="field-control fundamental-period-field">
          <span>Chart quarters</span>
          <select
            disabled={!isEnabled}
            value={inspection[periodsField]}
            onChange={(event) => onChange(periodsField, event.target.value)}
          >
            {FUNDAMENTAL_INSPECTION_PERIOD_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      </div>
      {isEnabled && validationMessage && (
        <p className="validation-message fundamental-window-validation" role="status">
          {validationMessage}
        </p>
      )}
    </div>
  )
}
