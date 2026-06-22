import { useState } from 'react'
import { Header } from './components/Header'
import type { AppPage } from './components/NavigationTabs'
import { GuidePage } from './pages/GuidePage'
import { StockFilterPage } from './pages/StockFilterPage'
import './styles/app.css'

function App() {
  const [activePage, setActivePage] = useState<AppPage>('guide')

  return (
    <div className="app-shell">
      <Header activePage={activePage} onNavigate={setActivePage} />
      {activePage === 'guide' ? (
        <GuidePage onOpenFilter={() => setActivePage('filter')} />
      ) : (
        <StockFilterPage />
      )}
    </div>
  )
}

export default App
