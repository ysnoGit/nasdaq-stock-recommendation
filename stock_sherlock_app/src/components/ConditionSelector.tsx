import { CONDITION_OPTIONS } from '../config/screeningOptions'
import type { ConditionCategory } from '../types/screening'

interface ConditionSelectorProps {
  selectedConditions: Set<ConditionCategory>
  onToggle: (category: ConditionCategory) => void
}

export function ConditionSelector({
  selectedConditions,
  onToggle,
}: ConditionSelectorProps) {
  const hasSelection = selectedConditions.size > 0
  const hasFundamental = selectedConditions.has('annualFundamental')
    || selectedConditions.has('quarterlyFundamental')
  const hasMarket = [...selectedConditions].some((category) =>
    category === 'volume' || category === 'dailyPrice' || category === 'weeklyPrice',
  )

  return (
    <section className="filter-section" aria-labelledby="conditions-title">
      <div className="section-heading-row">
        <div>
          <p className="section-kicker">Screen logic</p>
          <h2 id="conditions-title">Conditions</h2>
        </div>
        <span className="selection-count" aria-live="polite">
          {selectedConditions.size} selected
        </span>
      </div>

      <div className="condition-grid">
        {CONDITION_OPTIONS.map(({ category, conditionRange, label }) => {
          const isFundamental = category === 'annualFundamental'
            || category === 'quarterlyFundamental'
          const isDisabled = (hasFundamental && !isFundamental)
            || (hasMarket && isFundamental)

          return (
          <label
            className={`condition-option${isDisabled ? ' condition-option-disabled' : ''}`}
            key={category}
          >
            <input
              checked={selectedConditions.has(category)}
              disabled={isDisabled}
              onChange={() => onToggle(category)}
              type="checkbox"
            />
            <span className="condition-copy">
              <span>{label}</span>
              <small>{conditionRange}</small>
            </span>
          </label>
          )
        })}
      </div>

      {!hasSelection && (
        <p className="validation-message" role="status">
          Select at least one condition to enable filtering.
        </p>
      )}
    </section>
  )
}
