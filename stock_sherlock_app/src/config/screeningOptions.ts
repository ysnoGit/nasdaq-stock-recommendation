import type {
  ConditionCategory,
  FundamentalInspection,
  ScreeningParameters,
  SelectOption,
} from '../types/screening'

export const MARKET_INSPECTION_MIN_DATE = '2026-05-28'

export const CONDITION_OPTIONS: Array<{
  category: ConditionCategory
  conditionRange: string
  label: string
}> = [
  { category: 'annualFundamental', conditionRange: 'A', label: 'Annual Fundamental' },
  { category: 'quarterlyFundamental', conditionRange: 'B', label: 'Quarterly Fundamental' },
  { category: 'volume', conditionRange: 'C–D', label: 'Volume' },
  { category: 'dailyPrice', conditionRange: 'E–F', label: 'Daily Price' },
  { category: 'weeklyPrice', conditionRange: 'G–H', label: 'Weekly Price' },
]

const percentageOptions = (values: number[]): SelectOption[] =>
  values.map((value) => ({ label: `${value}%`, value: String(value) }))

const numberOptions = (values: number[], suffix = ''): SelectOption[] =>
  values.map((value) => ({ label: `${value}${suffix}`, value: String(value) }))

export const ANNUAL_GROWTH_OPTIONS = percentageOptions([3, 5, 10, 15, 20])
export const ANNUAL_YEARS_OPTIONS = numberOptions([2, 3, 4])
export const QUARTERLY_GROWTH_OPTIONS = percentageOptions([3, 5, 10, 15, 20])
export const QUARTER_COUNT_OPTIONS = numberOptions([2, 3, 4, 5])
export const VOLUME_RATIO_OPTIONS = numberOptions([5, 10, 15, 20, 25], '×')
export const SURGE_DAYS_OPTIONS = numberOptions([3, 5, 7])
export const DAILY_TOLERANCE_OPTIONS = percentageOptions([1, 2, 3])
export const WEEKLY_TOLERANCE_OPTIONS = percentageOptions([1, 2, 3, 4])
export const FUNDAMENTAL_INSPECTION_PERIOD_OPTIONS = numberOptions([1, 2, 3, 4, 5, 6, 7, 8])
export const CALENDAR_QUARTER_OPTIONS = [1, 2, 3, 4].map((value) => ({
  label: `Q${value}`,
  value: String(value),
}))

export const DEFAULT_FUNDAMENTAL_INSPECTION: FundamentalInspection = {
  throughYear: '',
  throughQuarter: '',
  annualInspectionPeriods: '4',
  quarterlyInspectionPeriods: '4',
}

export const DEFAULT_PARAMETERS: ScreeningParameters = {
  annualGrowthPct: '3',
  annualYears: '4',
  quarterlyGrowthPct: '5',
  quarterCount: '3',
  volumeRatioThreshold: '5',
  volumeSurgeMinDays: '3',
  dailyMaTolerancePct: '3',
  weeklyMaTolerancePct: '4',
}
