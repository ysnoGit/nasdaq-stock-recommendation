import { getSupabaseClient } from '../lib/supabase'
import type {
  EvaluationStatus,
  ResultChartPoint,
  ScreeningRequest,
  SelectedStock,
} from '../types/screening'

interface CountRpcRow {
  inspection_date: string
  selected_company_count: number | null
  evaluation_status: EvaluationStatus
}

interface DetailRpcRow {
  evaluation_status: EvaluationStatus
  inspection_date: string
  gvkey: string | null
  iid: string | null
  ticker: string | null
  company_name: string | null
  open_price: number | null
  high_price: number | null
  low_price: number | null
  close_price: number | null
  volume: number | null
}

function rpcParameters(request: ScreeningRequest) {
  const conditions = new Set(request.selectedConditions)
  const parameters = request.parameters

  return {
    p_use_annual_fundamental: conditions.has('annualFundamental'),
    p_use_quarterly_fundamental: conditions.has('quarterlyFundamental'),
    p_use_volume: conditions.has('volume'),
    p_use_daily_price: conditions.has('dailyPrice'),
    p_use_weekly_price: conditions.has('weeklyPrice'),
    p_annual_growth_pct: Number(parameters.annualGrowthPct),
    p_annual_years: Number(parameters.annualYears),
    p_quarterly_growth_pct: Number(parameters.quarterlyGrowthPct),
    p_quarter_count: Number(parameters.quarterCount),
    p_volume_ratio_threshold: Number(parameters.volumeRatioThreshold),
    p_volume_surge_min_days: Number(parameters.volumeSurgeMinDays),
    p_daily_ma_tolerance_pct: Number(parameters.dailyMaTolerancePct),
    p_weekly_ma_tolerance_pct: Number(parameters.weeklyMaTolerancePct),
    p_exclude_universe: false,
  }
}

function fundamentalQuarterEnd(request: ScreeningRequest): string {
  const year = request.fundamentalInspection.throughYear
  const quarter = Number(request.fundamentalInspection.throughQuarter)
  const monthAndDay = ['03-31', '06-30', '09-30', '12-31'][quarter - 1]
  return `${year}-${monthAndDay}`
}

export async function fetchCompanyCounts(
  request: ScreeningRequest,
): Promise<ResultChartPoint[]> {
  const isAnnual = request.selectedConditions.includes('annualFundamental')
  const isQuarterly = request.selectedConditions.includes('quarterlyFundamental')
  const { data, error } = await getSupabaseClient().rpc('screen_company_counts', {
    ...rpcParameters(request),
    p_start_date: request.dateRange.startDate,
    p_end_date: request.dateRange.endDate,
    p_fundamental_through_date: fundamentalQuarterEnd(request),
    p_fundamental_inspection_periods: Number(
      isAnnual
        ? request.fundamentalInspection.annualInspectionPeriods
        : isQuarterly
          ? request.fundamentalInspection.quarterlyInspectionPeriods
          : 4,
    ),
  })

  if (error) throw new Error(error.message)
  return ((data ?? []) as CountRpcRow[]).map((row) => ({
    date: row.inspection_date,
    selectedCompanyCount: row.selected_company_count,
    evaluationStatus: row.evaluation_status,
  }))
}

export async function fetchCompaniesForDate(
  request: ScreeningRequest,
  inspectionDate: string,
): Promise<{ status: EvaluationStatus; stocks: SelectedStock[] }> {
  const { data, error } = await getSupabaseClient().rpc(
    'screen_companies_for_date',
    {
      ...rpcParameters(request),
      p_inspection_date: inspectionDate,
    },
  )

  if (error) throw new Error(error.message)
  const rows = (data ?? []) as DetailRpcRow[]
  const status = rows[0]?.evaluation_status ?? 'complete'
  const stocks = rows
    .filter((row) => row.gvkey !== null)
    .map((row) => ({
      date: row.inspection_date,
      companyName: row.company_name ?? 'Unknown company',
      ticker: row.ticker ?? '—',
      open: row.open_price,
      high: row.high_price,
      low: row.low_price,
      close: row.close_price,
      volume: row.volume,
    }))

  return { status, stocks }
}
