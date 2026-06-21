import { useMemo, useState } from 'react'
import { Filter } from 'lucide-react'
import { ConditionSelector } from '../components/ConditionSelector'
import { Header } from '../components/Header'
import { ParameterPanel } from '../components/ParameterPanel'
import { ResultChartSection } from '../components/ResultChartSection'
import { SelectedStockListSection } from '../components/SelectedStockListSection'
import {
  DEFAULT_FUNDAMENTAL_INSPECTION,
  DEFAULT_PARAMETERS,
  MARKET_INSPECTION_MIN_DATE,
} from '../config/screeningOptions'
import {
  fetchCompaniesForDate,
  fetchCompanyCounts,
} from '../services/screening'
import type {
  ConditionCategory,
  DateRange,
  EvaluationStatus,
  FundamentalInspection,
  ParameterValue,
  ResultChartPoint,
  ScreeningParameters,
  ScreeningRequest,
  SelectedStock,
} from '../types/screening'

const MILLISECONDS_PER_DAY = 86_400_000
const MAX_INSPECTION_DAYS = 90

function toDateInputValue(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function createInitialDateRange(): DateRange {
  const endDate = new Date()
  const startDate = new Date(endDate)
  startDate.setDate(startDate.getDate() - 29)

  return {
    startDate: toDateInputValue(startDate),
    endDate: toDateInputValue(endDate),
  }
}

function createInitialFundamentalInspection(): FundamentalInspection {
  const now = new Date()
  const currentQuarter = Math.floor(now.getMonth() / 3) + 1
  const throughQuarter = currentQuarter === 1 ? 4 : currentQuarter - 1
  const throughYear = currentQuarter === 1 ? now.getFullYear() - 1 : now.getFullYear()
  return {
    ...DEFAULT_FUNDAMENTAL_INSPECTION,
    throughYear: String(throughYear),
    throughQuarter: String(throughQuarter),
  }
}

function quarterEndDate(year: number, quarter: number): string {
  const monthAndDay = ['03-31', '06-30', '09-30', '12-31'][quarter - 1]
  return `${year}-${monthAndDay}`
}

function validateDateRange(
  dateRange: DateRange,
  maximumDate: string,
  isFundamentalOnly: boolean,
  minimumDate?: string,
): {
  inclusiveDayCount: number | null
  message: string | null
} {
  if (!dateRange.endDate) {
    return { inclusiveDayCount: null, message: 'Choose an end date.' }
  }

  if (!isFundamentalOnly && !dateRange.startDate) {
    return { inclusiveDayCount: null, message: 'Choose both inspection dates.' }
  }

  if (
    dateRange.endDate > maximumDate ||
    (!isFundamentalOnly && dateRange.startDate > maximumDate)
  ) {
    return { inclusiveDayCount: null, message: 'Inspection dates cannot be in the future.' }
  }

  if (isFundamentalOnly) {
    return { inclusiveDayCount: 1, message: null }
  }

  if (
    minimumDate &&
    (dateRange.startDate < minimumDate || dateRange.endDate < minimumDate)
  ) {
    return {
      inclusiveDayCount: null,
      message: 'Market inspection dates cannot be before May 28, 2026.',
    }
  }

  const startTime = new Date(`${dateRange.startDate}T00:00:00`).getTime()
  const endTime = new Date(`${dateRange.endDate}T00:00:00`).getTime()

  if (endTime < startTime) {
    return { inclusiveDayCount: null, message: 'End date must be on or after start date.' }
  }

  const inclusiveDayCount = Math.round((endTime - startTime) / MILLISECONDS_PER_DAY) + 1
  if (inclusiveDayCount > MAX_INSPECTION_DAYS) {
    return {
      inclusiveDayCount,
      message: 'Inspection window cannot exceed 90 calendar days.',
    }
  }

  return { inclusiveDayCount, message: null }
}

export function StockFilterPage() {
  const maximumDate = toDateInputValue(new Date())
  const [selectedConditions, setSelectedConditions] = useState<Set<ConditionCategory>>(
    new Set(),
  )
  const [parameters, setParameters] =
    useState<ScreeningParameters>(DEFAULT_PARAMETERS)
  const [dateRange, setDateRange] = useState<DateRange>(createInitialDateRange)
  const [fundamentalInspection, setFundamentalInspection] =
    useState<FundamentalInspection>(createInitialFundamentalInspection)
  const [hasRunFilter, setHasRunFilter] = useState(false)
  const [chartData, setChartData] = useState<ResultChartPoint[]>([])
  const [selectedChartDate, setSelectedChartDate] = useState<string | null>(null)
  const [selectedStocks, setSelectedStocks] = useState<SelectedStock[]>([])
  const [submittedRequest, setSubmittedRequest] = useState<ScreeningRequest | null>(null)
  const [resultStatus, setResultStatus] = useState<EvaluationStatus | null>(null)
  const [isFiltering, setIsFiltering] = useState(false)
  const [isLoadingStocks, setIsLoadingStocks] = useState(false)
  const [filterError, setFilterError] = useState<string | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const isFundamentalScreen = selectedConditions.has('annualFundamental')
    || selectedConditions.has('quarterlyFundamental')
  const hasMarketSelection = [...selectedConditions].some((category) =>
    category === 'volume' || category === 'dailyPrice' || category === 'weeklyPrice',
  )
  const marketMinimumDate =
    hasMarketSelection
      ? MARKET_INSPECTION_MIN_DATE
      : undefined

  const dateValidation = useMemo(
    () =>
      validateDateRange(
        dateRange,
        maximumDate,
        false,
        marketMinimumDate,
      ),
    [dateRange, marketMinimumDate, maximumDate],
  )
  const fundamentalValidationMessage = useMemo(() => {
    if (!isFundamentalScreen) return null
    const year = Number(fundamentalInspection.throughYear)
    const quarter = Number(fundamentalInspection.throughQuarter)
    if (!Number.isInteger(year) || year < 1900 || year > 2100 || quarter < 1 || quarter > 4) {
      return 'Choose a valid inspection year and quarter.'
    }
    const currentQuarterStart = new Date()
    currentQuarterStart.setMonth(Math.floor(currentQuarterStart.getMonth() / 3) * 3, 1)
    currentQuarterStart.setHours(0, 0, 0, 0)
    const selectedQuarterEnd = new Date(`${quarterEndDate(year, quarter)}T00:00:00`)
    if (selectedQuarterEnd >= currentQuarterStart) {
      return 'Choose a completed calendar quarter.'
    }
    return null
  }, [fundamentalInspection, isFundamentalScreen])
  const canFilter = selectedConditions.size > 0
    && !(isFundamentalScreen ? fundamentalValidationMessage : dateValidation.message)
    && !isFiltering

  const toggleCondition = (category: ConditionCategory) => {
    const isFundamental = category === 'annualFundamental'
      || category === 'quarterlyFundamental'
    if (!isFundamental && !selectedConditions.has(category)) {
      setDateRange((current) => ({
        startDate:
          current.startDate < MARKET_INSPECTION_MIN_DATE
            ? MARKET_INSPECTION_MIN_DATE
            : current.startDate,
        endDate:
          current.endDate < MARKET_INSPECTION_MIN_DATE
            ? MARKET_INSPECTION_MIN_DATE
            : current.endDate,
      }))
    }

    setSelectedConditions((current) => {
      if (isFundamental) {
        return current.has(category)
          ? new Set<ConditionCategory>()
          : new Set<ConditionCategory>([category])
      }

      if (current.has('annualFundamental') || current.has('quarterlyFundamental')) return current

      const next = new Set(current)
      if (next.has(category)) {
        next.delete(category)
      } else {
        next.add(category)
      }
      return next
    })
  }

  const updateParameter = (
    id: keyof ScreeningParameters,
    value: ParameterValue,
  ) => {
    setParameters((current) => ({ ...current, [id]: value }))
  }

  const updateDate = (field: keyof DateRange, value: string) => {
    setDateRange((current) => ({ ...current, [field]: value }))
  }

  const updateFundamentalInspection = (
    field: keyof FundamentalInspection,
    value: string,
  ) => {
    setFundamentalInspection((current) => ({ ...current, [field]: value }))
  }

  const handleFilter = async () => {
    if (!canFilter) return

    const request: ScreeningRequest = {
      dateRange: { ...dateRange },
      fundamentalInspection: { ...fundamentalInspection },
      parameters: { ...parameters },
      selectedConditions: [...selectedConditions],
    }
    setIsFiltering(true)
    setFilterError(null)
    setDetailError(null)
    setResultStatus(null)
    setSelectedChartDate(null)
    setSelectedStocks([])
    try {
      const results = await fetchCompanyCounts(request)
      setChartData(results)
      setSubmittedRequest(request)
      setHasRunFilter(true)
    } catch (error) {
      setChartData([])
      setSubmittedRequest(null)
      setHasRunFilter(true)
      setFilterError(error instanceof Error ? error.message : 'Screening request failed.')
    } finally {
      setIsFiltering(false)
    }
  }

  const handleChartDateSelection = async (date: string) => {
    const chartPoint = chartData.find((point) => point.date === date)
    if (!chartPoint || !submittedRequest) return

    setSelectedChartDate(date)
    setSelectedStocks([])
    setDetailError(null)
    setResultStatus(chartPoint.evaluationStatus)
    if (chartPoint.evaluationStatus !== 'complete') return

    setIsLoadingStocks(true)
    try {
      const result = await fetchCompaniesForDate(submittedRequest, date)
      setResultStatus(result.status)
      setSelectedStocks(result.stocks)
    } catch (error) {
      setDetailError(error instanceof Error ? error.message : 'Company details failed to load.')
    } finally {
      setIsLoadingStocks(false)
    }
  }

  return (
    <div className="app-shell">
      <Header />

      <main className="dashboard-layout">
        <aside className="filter-panel" aria-label="Stock filter configuration">
          <ConditionSelector
            selectedConditions={selectedConditions}
            onToggle={toggleCondition}
          />
          <ParameterPanel
            dateRange={dateRange}
            fundamentalInspection={fundamentalInspection}
            fundamentalValidationMessage={fundamentalValidationMessage}
            inclusiveDayCount={dateValidation.inclusiveDayCount}
            maximumDate={maximumDate}
            minimumDate={marketMinimumDate}
            parameters={parameters}
            selectedConditions={selectedConditions}
            validationMessage={dateValidation.message}
            onDateChange={updateDate}
            onFundamentalInspectionChange={updateFundamentalInspection}
            onParameterChange={updateParameter}
          />

          <div className="filter-action">
            <button
              className="filter-button"
              disabled={!canFilter}
              type="button"
              onClick={handleFilter}
            >
              <Filter aria-hidden="true" size={17} />
              {isFiltering ? 'Filtering…' : 'Filter'}
            </button>
          </div>
        </aside>

        <div className="results-column">
          <ResultChartSection
            data={chartData}
            errorMessage={filterError}
            hasRun={hasRunFilter}
            isLoading={isFiltering}
            useQuarterAxis={Boolean(
              submittedRequest?.selectedConditions.includes('annualFundamental')
              || submittedRequest?.selectedConditions.includes('quarterlyFundamental')
            )}
            selectedDate={selectedChartDate}
            onSelectDate={handleChartDateSelection}
          />
          <SelectedStockListSection
            hasRun={hasRunFilter}
            isLoading={isLoadingStocks}
            errorMessage={detailError}
            evaluationStatus={resultStatus}
            useQuarterLabel={Boolean(
              submittedRequest?.selectedConditions.includes('annualFundamental')
              || submittedRequest?.selectedConditions.includes('quarterlyFundamental')
            )}
            selectedDate={selectedChartDate}
            stocks={selectedStocks}
          />
        </div>
      </main>
    </div>
  )
}
