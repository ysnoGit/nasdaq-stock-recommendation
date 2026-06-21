import {
  ANNUAL_GROWTH_OPTIONS,
  ANNUAL_YEARS_OPTIONS,
  DAILY_TOLERANCE_OPTIONS,
  QUARTER_COUNT_OPTIONS,
  QUARTERLY_GROWTH_OPTIONS,
  SURGE_DAYS_OPTIONS,
  VOLUME_RATIO_OPTIONS,
  WEEKLY_TOLERANCE_OPTIONS,
} from '../config/screeningOptions'
import type {
  ConditionCategory,
  DateRange,
  FundamentalInspection,
  ParameterValue,
  ScreeningParameters,
} from '../types/screening'
import { DateRangeSelector } from './DateRangeSelector'
import { FundamentalInspectionWindow } from './FundamentalInspectionWindow'
import { ParameterGroup } from './ParameterGroup'

interface ParameterPanelProps {
  dateRange: DateRange
  fundamentalInspection: FundamentalInspection
  fundamentalValidationMessage: string | null
  inclusiveDayCount: number | null
  maximumDate: string
  minimumDate?: string
  parameters: ScreeningParameters
  selectedConditions: Set<ConditionCategory>
  validationMessage: string | null
  onDateChange: (field: keyof DateRange, value: string) => void
  onFundamentalInspectionChange: (field: keyof FundamentalInspection, value: string) => void
  onParameterChange: (id: keyof ScreeningParameters, value: ParameterValue) => void
}

export function ParameterPanel({
  dateRange,
  fundamentalInspection,
  fundamentalValidationMessage,
  inclusiveDayCount,
  maximumDate,
  minimumDate,
  parameters,
  selectedConditions,
  validationMessage,
  onDateChange,
  onFundamentalInspectionChange,
  onParameterChange,
}: ParameterPanelProps) {
  const updateParameter = (id: string, value: ParameterValue) =>
    onParameterChange(id as keyof ScreeningParameters, value)
  const hasMarketCondition = [...selectedConditions].some((condition) =>
    condition === 'volume' || condition === 'dailyPrice' || condition === 'weeklyPrice',
  )

  return (
    <section className="filter-section parameters-section" aria-labelledby="parameters-title">
      <div className="section-heading-row">
        <div>
          <p className="section-kicker">Configuration</p>
          <h2 id="parameters-title">Parameters</h2>
        </div>
      </div>

      <DateRangeSelector
        dateRange={dateRange}
        disabled={!hasMarketCondition}
        inclusiveDayCount={inclusiveDayCount}
        maximumDate={maximumDate}
        minimumDate={minimumDate}
        validationMessage={validationMessage}
        onChange={onDateChange}
      />

      <FundamentalInspectionWindow
        inspection={fundamentalInspection}
        selectedConditions={selectedConditions}
        validationMessage={fundamentalValidationMessage}
        onChange={onFundamentalInspectionChange}
      />

      <ParameterGroup
        conditionRange="A"
        disabled={!selectedConditions.has('annualFundamental')}
        title="Annual fundamental"
        fields={[
          {
            id: 'annualGrowthPct',
            label: 'Growth threshold',
            options: ANNUAL_GROWTH_OPTIONS,
            value: parameters.annualGrowthPct,
          },
          {
            id: 'annualYears',
            label: 'Annual years',
            options: ANNUAL_YEARS_OPTIONS,
            value: parameters.annualYears,
          },
        ]}
        onChange={updateParameter}
      />

      <ParameterGroup
        conditionRange="B"
        disabled={!selectedConditions.has('quarterlyFundamental')}
        title="Quarterly fundamental"
        fields={[
          {
            id: 'quarterlyGrowthPct',
            label: 'Growth threshold',
            options: QUARTERLY_GROWTH_OPTIONS,
            value: parameters.quarterlyGrowthPct,
          },
          {
            id: 'quarterCount',
            label: 'Quarter count',
            options: QUARTER_COUNT_OPTIONS,
            value: parameters.quarterCount,
          },
        ]}
        onChange={updateParameter}
      />

      <ParameterGroup
        conditionRange="C–D"
        disabled={!selectedConditions.has('volume')}
        title="Volume"
        fields={[
          {
            id: 'volumeRatioThreshold',
            label: 'Volume ratio',
            options: VOLUME_RATIO_OPTIONS,
            value: parameters.volumeRatioThreshold,
          },
          {
            id: 'volumeSurgeMinDays',
            label: 'Minimum surge days',
            options: SURGE_DAYS_OPTIONS,
            value: parameters.volumeSurgeMinDays,
          },
        ]}
        onChange={updateParameter}
      />

      <ParameterGroup
        conditionRange="E–F"
        disabled={!selectedConditions.has('dailyPrice')}
        title="Daily price"
        fields={[
          {
            id: 'dailyMaTolerancePct',
            label: 'MA tolerance',
            options: DAILY_TOLERANCE_OPTIONS,
            value: parameters.dailyMaTolerancePct,
          },
        ]}
        onChange={updateParameter}
      />

      <ParameterGroup
        conditionRange="G–H"
        disabled={!selectedConditions.has('weeklyPrice')}
        title="Weekly price"
        fields={[
          {
            id: 'weeklyMaTolerancePct',
            label: 'MA tolerance',
            options: WEEKLY_TOLERANCE_OPTIONS,
            value: parameters.weeklyMaTolerancePct,
          },
        ]}
        onChange={updateParameter}
      />
    </section>
  )
}
