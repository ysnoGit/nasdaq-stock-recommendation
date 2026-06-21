import { useState } from 'react'
import { Check, Copy, TableProperties } from 'lucide-react'
import type { EvaluationStatus, SelectedStock } from '../types/screening'

interface SelectedStockListSectionProps {
  hasRun: boolean
  isLoading: boolean
  errorMessage: string | null
  evaluationStatus: EvaluationStatus | null
  useQuarterLabel: boolean
  selectedDate: string | null
  stocks: SelectedStock[]
}

const priceFormatter = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const volumeFormatter = new Intl.NumberFormat('en-US', {
  notation: 'compact',
  maximumFractionDigits: 2,
})

const formatPrice = (value: number | null) =>
  value === null ? '—' : priceFormatter.format(value)

const formatVolume = (value: number | null) =>
  value === null ? '—' : volumeFormatter.format(value)

const cleanCell = (value: string | number | null) =>
  value === null ? '' : String(value).replace(/[\t\r\n]+/g, ' ')

async function writeClipboard(text: string): Promise<void> {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text)
    return
  }

  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  const copied = document.execCommand('copy')
  textarea.remove()
  if (!copied) throw new Error('Clipboard copy failed')
}

function pendingMessage(status: EvaluationStatus | null): string | null {
  if (status === 'pending_f') {
    return 'Awaiting the next trading session required to confirm Condition F.'
  }
  if (status === 'pending_h') {
    return 'Awaiting the following completed trading week required to confirm Condition H.'
  }
  if (status === 'no_market_session') {
    return 'This date is not an eligible market session.'
  }
  if (status === 'no_data') {
    return 'No fundamental records are available for this calendar quarter.'
  }
  return null
}

export function SelectedStockListSection({
  hasRun,
  isLoading,
  errorMessage,
  evaluationStatus,
  useQuarterLabel,
  selectedDate,
  stocks,
}: SelectedStockListSectionProps) {
  const [copyFeedback, setCopyFeedback] = useState<{
    date: string | null
    state: 'idle' | 'copied' | 'error'
  }>({ date: null, state: 'idle' })
  const copyState = copyFeedback.date === selectedDate ? copyFeedback.state : 'idle'
  const statusMessage = pendingMessage(evaluationStatus)
  const selectedPeriod = selectedDate && useQuarterLabel
    ? `${selectedDate.slice(0, 4)} Q${Math.floor((Number(selectedDate.slice(5, 7)) - 1) / 3) + 1}`
    : selectedDate

  const copyTable = async () => {
    const headers = ['Company Name', 'Ticker', 'Open', 'High', 'Low', 'Close', 'Volume']
    const rows = stocks.map((stock) => [
      stock.companyName,
      stock.ticker,
      stock.open,
      stock.high,
      stock.low,
      stock.close,
      stock.volume,
    ])
    const text = [headers, ...rows]
      .map((row) => row.map(cleanCell).join('\t'))
      .join('\n')

    try {
      await writeClipboard(text)
      setCopyFeedback({ date: selectedDate, state: 'copied' })
      window.setTimeout(
        () => setCopyFeedback({ date: selectedDate, state: 'idle' }),
        1800,
      )
    } catch {
      setCopyFeedback({ date: selectedDate, state: 'error' })
    }
  }

  return (
    <section className="result-section" aria-labelledby="selected-stock-list-title">
      <div className="result-section-heading">
        <div>
          <span className="result-section-icon" aria-hidden="true">
            <TableProperties size={19} />
          </span>
          <h2 id="selected-stock-list-title">Selected Stock List</h2>
        </div>
        <button
          aria-label={copyState === 'copied' ? 'Stock list copied' : 'Copy selected stock list'}
          className={`table-copy-button${copyState === 'copied' ? ' table-copy-button-success' : ''}`}
          disabled={!selectedDate || stocks.length === 0 || evaluationStatus !== 'complete'}
          onClick={copyTable}
          title={copyState === 'error' ? 'Copy failed' : copyState === 'copied' ? 'Copied' : 'Copy table'}
          type="button"
        >
          {copyState === 'copied' ? <Check aria-hidden="true" size={17} /> : <Copy aria-hidden="true" size={17} />}
        </button>
      </div>

      {isLoading ? (
        <div className="result-empty-state result-empty-state-compact">
          <TableProperties aria-hidden="true" size={27} strokeWidth={1.6} />
          <p>Loading selected companies…</p>
        </div>
      ) : errorMessage ? (
        <div className="result-empty-state result-empty-state-compact result-error-state" role="alert">
          <p>{errorMessage}</p>
        </div>
      ) : !hasRun ? (
        <div className="result-empty-state result-empty-state-compact">
          <TableProperties aria-hidden="true" size={27} strokeWidth={1.6} />
          <p>Run Filter to view results</p>
        </div>
      ) : !selectedDate ? (
        <div className="result-empty-state result-empty-state-compact">
          <TableProperties aria-hidden="true" size={27} strokeWidth={1.6} />
          <p>Select a chart point to view companies</p>
        </div>
      ) : statusMessage ? (
        <div className="result-empty-state result-empty-state-compact pending-state">
          <TableProperties aria-hidden="true" size={27} strokeWidth={1.6} />
          <p>{evaluationStatus === 'no_data' ? 'No source data' : 'Confirmation pending'}</p>
          <span>{statusMessage}</span>
        </div>
      ) : (
        <div className="stock-list-content">
          <dl className="stock-list-summary">
            <div>
              <dt>{useQuarterLabel ? 'Selected Quarter' : 'Selected Date'}</dt>
              <dd>{selectedPeriod}</dd>
            </div>
            <div>
              <dt>Selected Companies</dt>
              <dd>{stocks.length}</dd>
            </div>
            <div>
              <dt>Currency</dt>
              <dd>USD</dd>
            </div>
          </dl>

          {stocks.length === 0 ? (
            <div className="stock-list-zero">No companies passed on this completed date.</div>
          ) : (
            <div className="stock-table-scroll" data-testid="stock-table-scroll">
              <table className="stock-table">
                <thead>
                  <tr>
                    <th scope="col">Company Name</th>
                    <th scope="col">Ticker</th>
                    <th scope="col">Open</th>
                    <th scope="col">High</th>
                    <th scope="col">Low</th>
                    <th scope="col">Close</th>
                    <th scope="col">Volume</th>
                  </tr>
                </thead>
                <tbody>
                  {stocks.map((stock) => (
                    <tr key={`${stock.date}-${stock.ticker}`}>
                      <td>{stock.companyName}</td>
                      <td className="ticker-cell">{stock.ticker}</td>
                      <td>{formatPrice(stock.open)}</td>
                      <td>{formatPrice(stock.high)}</td>
                      <td>{formatPrice(stock.low)}</td>
                      <td>{formatPrice(stock.close)}</td>
                      <td>{formatVolume(stock.volume)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
