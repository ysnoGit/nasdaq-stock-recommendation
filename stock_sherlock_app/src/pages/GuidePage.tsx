import {
  ArrowRight,
  BarChart3,
  CalendarRange,
  CheckCircle2,
  Cloud,
  Code2,
  Database,
  ExternalLink,
  ListFilter,
  TableProperties,
} from 'lucide-react'

type GuidePageProps = {
  onOpenFilter: () => void
}

type ConditionGuideGroup = {
  code: string
  title: string
  summary: string
  logic?: string
  conditions?: Array<{
    code: string
    name: string
    description: string
  }>
  parameters: string[]
}

const conditionGroups: ConditionGuideGroup[] = [
  {
    code: 'A',
    title: 'Annual Fundamental',
    summary: 'Finds companies with sustained annual revenue and operating-income growth.',
    logic: 'Both growth measures must meet the threshold in every requested consecutive fiscal year.',
    parameters: ['Growth: 3%, 5%, 10%, 15%, 20%', 'Years: 2, 3, 4'],
  },
  {
    code: 'B',
    title: 'Quarterly Fundamental',
    summary: 'Finds companies with consistent year-over-year quarterly growth.',
    logic: 'Revenue and operating-income growth must pass in every requested consecutive fiscal quarter.',
    parameters: ['Growth: 3%, 5%, 10%, 15%, 20%', 'Quarters: 2, 3, 4, 5'],
  },
  {
    code: 'C-D',
    title: 'Volume',
    summary: 'Looks for unusually high trading activity that repeats within a recent window.',
    conditions: [
      {
        code: 'C',
        name: 'Current volume surge',
        description: 'Checks whether the inspection day\'s volume reaches the selected multiple of the average from the previous 30 valid trading days.',
      },
      {
        code: 'D',
        name: 'Repeated volume surge',
        description: 'Checks whether that same security reached the selected volume multiple on at least the chosen number of days during the trailing three calendar months.',
      },
    ],
    parameters: ['Volume ratio: 5x, 10x, 15x, 20x, 25x', 'Minimum surge days: 3, 5, 7'],
  },
  {
    code: 'E-F',
    title: 'Daily Price',
    summary: 'Detects tightly clustered daily moving averages followed by a bullish crossover.',
    conditions: [
      {
        code: 'E',
        name: 'Daily moving-average setup',
        description: 'Checks whether complete MA20, MA50, and MA100 values are all within the selected pairwise tolerance. Their order does not affect this setup check.',
      },
      {
        code: 'F',
        name: 'Next-session crossover',
        description: 'Confirms that MA20 is at or below MA50 on the E date, then moves above MA50 on the immediately following eligible trading session.',
      },
    ],
    parameters: ['MA tolerance: 1%, 2%, 3%'],
  },
  {
    code: 'G-H',
    title: 'Weekly Price',
    summary: 'Applies the same setup-and-confirmation idea to completed trading weeks.',
    conditions: [
      {
        code: 'G',
        name: 'Weekly moving-average setup',
        description: 'Checks whether complete weekly MA5, MA10, and MA30 values are all within the selected pairwise tolerance in a completed official trading week.',
      },
      {
        code: 'H',
        name: 'Following-week crossover',
        description: 'Confirms that MA10 is at or below MA30 in the G week, then moves above MA30 in the following completed official trading week.',
      },
    ],
    parameters: ['MA tolerance: 1%, 2%, 3%, 4%'],
  },
]

export function GuidePage({ onOpenFilter }: GuidePageProps) {
  return (
    <main className="guide-page">
      <section className="guide-intro" aria-labelledby="guide-title">
        <div>
          <p className="guide-eyebrow">Explainable stock screening</p>
          <h2 id="guide-title">How Stock Sherlock works</h2>
          <p className="guide-lead">
            Stock Sherlock turns fundamental growth, unusual volume, and moving-average
            confirmations into an auditable company shortlist. You choose the evidence;
            the app shows when and why each company qualifies.
          </p>
        </div>
        <button className="guide-primary-action" type="button" onClick={onOpenFilter}>
          Open Stock Filter
          <ArrowRight aria-hidden="true" size={17} />
        </button>
      </section>

      <section className="guide-section" aria-labelledby="workflow-title">
        <div className="guide-section-heading">
          <p className="guide-eyebrow">Screening workflow</p>
          <h2 id="workflow-title">From question to shortlist</h2>
        </div>
        <ol className="workflow-list">
          <li>
            <span className="workflow-number">1</span>
            <div><strong>Choose evidence</strong><span>Select one fundamental screen or combine market conditions.</span></div>
          </li>
          <li>
            <span className="workflow-number">2</span>
            <div><strong>Set thresholds and time</strong><span>Pick the strictness and inspection window that match your research question.</span></div>
          </li>
          <li>
            <span className="workflow-number">3</span>
            <div><strong>Inspect the result</strong><span>Compare company counts over time, then open a point to review its securities.</span></div>
          </li>
        </ol>
      </section>

      <section className="guide-section" aria-labelledby="conditions-title">
        <div className="guide-section-heading guide-heading-with-note">
          <div>
            <p className="guide-eyebrow">Conditions and choices</p>
            <h2 id="conditions-title">What each signal means</h2>
          </div>
          <p>Annual and quarterly fundamentals run independently. Market conditions C-H can be combined.</p>
        </div>
        <div className="condition-guide-grid">
          {conditionGroups.map((condition) => (
            <article className="condition-guide-item" key={condition.code}>
              <div className="condition-guide-title">
                <span>{condition.code}</span>
                <h3>{condition.title}</h3>
              </div>
              <p>{condition.summary}</p>
              {condition.conditions ? (
                <div className="condition-breakdown">
                  {condition.conditions.map((item) => (
                    <div className="condition-breakdown-row" key={item.code}>
                      <span>{item.code}</span>
                      <div>
                        <strong>{item.name}</strong>
                        <p>{item.description}</p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="condition-guide-logic">{condition.logic}</p>
              )}
              <ul className="parameter-choice-list" aria-label={`${condition.title} choices`}>
                {condition.parameters.map((parameter) => <li key={parameter}>{parameter}</li>)}
              </ul>
            </article>
          ))}
        </div>
      </section>

      <section className="guide-section guide-interpretation" aria-labelledby="results-title">
        <div className="guide-section-heading">
          <p className="guide-eyebrow">Reading the output</p>
          <h2 id="results-title">Interpret the chart and table together</h2>
        </div>
        <div className="interpretation-grid">
          <div>
            <span className="guide-icon"><BarChart3 aria-hidden="true" size={20} /></span>
            <h3>Selected Company Count</h3>
            <p>Each point is the number of distinct companies that pass on that inspection anchor. Fundamental screens use calendar-quarter anchors; market screens use trading dates.</p>
          </div>
          <div>
            <span className="guide-icon"><TableProperties aria-hidden="true" size={20} /></span>
            <h3>Selected Stock List</h3>
            <p>Select a chart point to see one preferred security per passing company, including ticker and available market fields. The copy button exports the visible table.</p>
          </div>
          <div>
            <span className="guide-icon"><CalendarRange aria-hidden="true" size={20} /></span>
            <h3>Confirmation timing</h3>
            <p>Daily F and weekly H require a later observation. Their result belongs to the original E or G setup date; unavailable confirmation is reported as pending, not as zero.</p>
          </div>
        </div>
      </section>

      <section className="guide-section guide-value-section" aria-labelledby="value-title">
        <div className="guide-section-heading">
          <p className="guide-eyebrow">Why this project matters</p>
          <h2 id="value-title">A repeatable answer to a noisy research problem</h2>
        </div>
        <div className="guide-value-grid">
          <p>Manual screeners often hide timing assumptions and make multi-signal research difficult to reproduce. Stock Sherlock separates setup dates from confirmation dates, exposes every user-controlled threshold, and preserves the same rules from data processing to the serving layer.</p>
          <ul>
            <li><CheckCircle2 aria-hidden="true" size={17} />Parameter-driven, explainable screening</li>
            <li><CheckCircle2 aria-hidden="true" size={17} />Point-in-time daily and weekly confirmation logic</li>
            <li><CheckCircle2 aria-hidden="true" size={17} />Cloud pipeline with validation and stable serving contracts</li>
          </ul>
        </div>
        <aside className="guide-data-note">
          <strong>Data note</strong>
          <span>Fundamental history currently uses fiscal period-end dates because filing publication dates are not available in the source dataset. Treat historical fundamental results as research signals, not investment advice.</span>
        </aside>
      </section>

      <section className="guide-section guide-stack-section" aria-labelledby="stack-title">
        <div className="guide-section-heading">
          <p className="guide-eyebrow">Implementation</p>
          <h2 id="stack-title">Built as a production-style data application</h2>
        </div>
        <div className="stack-grid">
          <div><Database aria-hidden="true" size={19} /><strong>Data</strong><span>WRDS Compustat, Python, DuckDB, Parquet</span></div>
          <div><Cloud aria-hidden="true" size={19} /><strong>Cloud</strong><span>AWS EC2, S3, EventBridge, SSM, Amplify</span></div>
          <div><ListFilter aria-hidden="true" size={19} /><strong>Serving</strong><span>Supabase PostgreSQL and controlled RPC functions</span></div>
          <div><Code2 aria-hidden="true" size={19} /><strong>Frontend</strong><span>React, TypeScript, Vite, Recharts</span></div>
        </div>
        <footer className="guide-footer">
          <span>Created by <strong>ysno</strong></span>
          <a href="https://github.com/ysnoGit/nasdaq-stock-recommendation" target="_blank" rel="noreferrer">
            <ExternalLink aria-hidden="true" size={17} /> View repository
          </a>
        </footer>
      </section>
    </main>
  )
}
