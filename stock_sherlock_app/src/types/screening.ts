export type ConditionCategory =
  | 'annualFundamental'
  | 'quarterlyFundamental'
  | 'volume'
  | 'dailyPrice'
  | 'weeklyPrice'

export type ParameterValue = string

export interface SelectOption {
  label: string
  value: ParameterValue
}

export interface ScreeningParameters {
  annualGrowthPct: ParameterValue
  annualYears: ParameterValue
  quarterlyGrowthPct: ParameterValue
  quarterCount: ParameterValue
  volumeRatioThreshold: ParameterValue
  volumeSurgeMinDays: ParameterValue
  dailyMaTolerancePct: ParameterValue
  weeklyMaTolerancePct: ParameterValue
}

export interface DateRange {
  startDate: string
  endDate: string
}

export interface FundamentalInspection {
  throughYear: ParameterValue
  throughQuarter: ParameterValue
  annualInspectionPeriods: ParameterValue
  quarterlyInspectionPeriods: ParameterValue
}

export interface ResultChartPoint {
  date: string
  selectedCompanyCount: number | null
  evaluationStatus: EvaluationStatus
}

export type EvaluationStatus =
  | 'complete'
  | 'pending_f'
  | 'pending_h'
  | 'no_market_session'
  | 'no_data'

export interface SelectedStock {
  date: string
  companyName: string
  ticker: string
  open: number | null
  high: number | null
  low: number | null
  close: number | null
  volume: number | null
}

export interface ScreeningRequest {
  dateRange: DateRange
  fundamentalInspection: FundamentalInspection
  parameters: ScreeningParameters
  selectedConditions: ConditionCategory[]
}
