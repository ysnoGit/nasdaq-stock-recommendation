import { SearchCheck } from 'lucide-react'
import { NavigationTabs, type AppPage } from './NavigationTabs'

type HeaderProps = {
  activePage: AppPage
  onNavigate: (page: AppPage) => void
}

export function Header({ activePage, onNavigate }: HeaderProps) {
  return (
    <header className="app-header">
      <div className="brand-lockup">
        <span className="brand-mark" aria-hidden="true">
          <SearchCheck size={24} strokeWidth={2.2} />
        </span>
        <h1>Stock Sherlock</h1>
      </div>
      <NavigationTabs activePage={activePage} onNavigate={onNavigate} />
    </header>
  )
}
