# Stock Sherlock Frontend

This folder is the isolated frontend workspace for **Stock Sherlock**, a NASDAQ stock-screening web application. Frontend work belongs here and remains separate from the repository's data pipeline, screening, and backtesting systems.

## Stack

- React
- TypeScript
- Vite
- AWS Amplify Hosting as the future deployment target
- Supabase as the future application-facing data layer

The stock filter calls controlled Supabase RPCs; heavy feature generation and
backtesting remain outside the browser in the existing EC2, Python, DuckDB,
S3, and batch workflows.

The current frontend implements the Stock Filter interface, live screening
counts, explicit pending F/H states, and selected-company details.

Market-condition inspection dates are constrained to the currently supported
serving-data window. Volume, Daily Price, and Weekly Price use an earliest date
of `2026-05-28`; Fundamental-only screening follows its separate end-date-only
rule.

## Local Development

Requirements: Node.js 20.19+ or 22.12+ and npm.

Create `.env.local` with the project's public browser credentials:

```bash
VITE_SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
VITE_SUPABASE_ANON_KEY=YOUR_PUBLIC_ANON_KEY
```

Never place the database URL, service-role key, or database password in a
`VITE_` variable.

```bash
cd stock_sherlock_app
npm install
npm run dev
```

Vite prints the local URL after startup, normally `http://localhost:5173`.

## Quality Checks

```bash
npm run lint
npm run build
```

The production build is written to `dist/`.

## Environment Variables

Copy `.env.example` to a local `.env` when Supabase integration is implemented later:

```bash
cp .env.example .env
```

Only the public Supabase URL and anonymous browser key belong in Vite variables. Never add a Supabase service-role key, database password, AWS credentials, or WRDS credentials to this frontend.

## AWS Amplify

The included `amplify.yml` uses `npm ci`, runs `npm run build`, and publishes `dist/`. Deployment is intentionally outside this setup task.

## Future UI Stage

Potential libraries should be selected only when their requirements are clear. Likely candidates include:

- A restrained component primitive library for accessible menus, dialogs, and popovers
- A date-picker library if native date controls are insufficient

Lucide React supplies the interface icon set, and Recharts renders the temporary mock result chart. No date-picker, styling framework, state-management, or Supabase client library is installed yet.
