import type {
  ParameterValue,
  SelectOption,
} from '../types/screening'

export interface ParameterField {
  id: string
  label: string
  options: SelectOption[]
  value: ParameterValue
}

interface ParameterGroupProps {
  conditionRange: string
  disabled: boolean
  fields: ParameterField[]
  title: string
  onChange: (id: string, value: ParameterValue) => void
}

export function ParameterGroup({
  conditionRange,
  disabled,
  fields,
  title,
  onChange,
}: ParameterGroupProps) {
  return (
    <fieldset className="parameter-group" disabled={disabled}>
      <legend className="sr-only">{title}</legend>
      <div className="parameter-group-heading">
        <span className="condition-range" aria-hidden="true">
          {conditionRange}
        </span>
        <div>
          <h3>{title}</h3>
          <p>{disabled ? 'Condition not selected' : 'Condition enabled'}</p>
        </div>
      </div>

      <div className="parameter-fields">
        {fields.map((field) => (
          <label className="field-control" key={field.id}>
            <span>{field.label}</span>
            <select
              value={field.value}
              onChange={(event) => onChange(field.id, event.target.value)}
            >
              {field.options.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>
    </fieldset>
  )
}
