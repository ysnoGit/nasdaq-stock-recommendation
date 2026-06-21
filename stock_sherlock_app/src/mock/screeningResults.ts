import type {
  DateRange,
  ResultChartPoint,
  SelectedStock,
} from '../types/screening'

const MOCK_RESULT_COUNTS = [7, 9, 6, 11, 8, 10, 5, 12, 9, 7, 10, 6]

const MOCK_STOCK_CATALOG: Array<Omit<SelectedStock, 'date'>> = [
  {
    companyName: 'Apple Inc.',
    ticker: 'AAPL',
    open: 198.32,
    high: 201.18,
    low: 197.65,
    close: 200.48,
    volume: 58_412_300,
  },
  {
    companyName: 'Microsoft Corporation',
    ticker: 'MSFT',
    open: 448.61,
    high: 452.9,
    low: 447.18,
    close: 451.37,
    volume: 21_806_500,
  },
  {
    companyName: 'NVIDIA Corporation',
    ticker: 'NVDA',
    open: 141.74,
    high: 145.22,
    low: 140.63,
    close: 144.81,
    volume: 198_337_200,
  },
  {
    companyName: 'Amazon.com, Inc.',
    ticker: 'AMZN',
    open: 218.44,
    high: 221.16,
    low: 217.08,
    close: 220.51,
    volume: 42_761_900,
  },
  {
    companyName: 'Alphabet Inc.',
    ticker: 'GOOGL',
    open: 187.25,
    high: 190.04,
    low: 186.83,
    close: 189.62,
    volume: 27_405_800,
  },
  {
    companyName: 'Meta Platforms, Inc.',
    ticker: 'META',
    open: 612.8,
    high: 619.42,
    low: 609.75,
    close: 617.16,
    volume: 16_932_400,
  },
  {
    companyName: 'Broadcom Inc.',
    ticker: 'AVGO',
    open: 236.18,
    high: 241.32,
    low: 234.96,
    close: 239.88,
    volume: 24_516_700,
  },
  {
    companyName: 'Costco Wholesale Corporation',
    ticker: 'COST',
    open: 981.4,
    high: 989.72,
    low: 977.16,
    close: 986.25,
    volume: 2_183_600,
  },
  {
    companyName: 'Tesla, Inc.',
    ticker: 'TSLA',
    open: 346.52,
    high: 355.76,
    low: 342.14,
    close: 352.61,
    volume: 112_604_900,
  },
  {
    companyName: 'Netflix, Inc.',
    ticker: 'NFLX',
    open: 1_214.8,
    high: 1_229.54,
    low: 1_208.36,
    close: 1_224.17,
    volume: 4_218_700,
  },
  {
    companyName: 'Advanced Micro Devices, Inc.',
    ticker: 'AMD',
    open: 126.48,
    high: 130.12,
    low: 125.91,
    close: 129.33,
    volume: 62_194_800,
  },
  {
    companyName: 'Adobe Inc.',
    ticker: 'ADBE',
    open: 418.72,
    high: 424.65,
    low: 416.38,
    close: 422.91,
    volume: 3_972_100,
  },
]

function formatDate(date: Date): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function createMockChartData(dateRange: DateRange): ResultChartPoint[] {
  const currentDate = new Date(`${dateRange.startDate}T12:00:00`)
  const endDate = new Date(`${dateRange.endDate}T12:00:00`)
  const points: ResultChartPoint[] = []

  while (currentDate <= endDate) {
    const dayOfWeek = currentDate.getDay()
    if (dayOfWeek !== 0 && dayOfWeek !== 6) {
      points.push({
        date: formatDate(currentDate),
        selectedCompanyCount:
          MOCK_RESULT_COUNTS[points.length % MOCK_RESULT_COUNTS.length],
        evaluationStatus: 'complete',
      })
    }
    currentDate.setDate(currentDate.getDate() + 1)
  }

  return points
}

export function createMockSelectedStocks(
  date: string,
  selectedCompanyCount: number,
): SelectedStock[] {
  return MOCK_STOCK_CATALOG.slice(0, selectedCompanyCount).map((stock) => ({
    ...stock,
    date,
  }))
}
