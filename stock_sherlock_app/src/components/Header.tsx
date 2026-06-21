import { SearchCheck } from 'lucide-react'
import { NavigationTabs } from './NavigationTabs'

export function Header() {
  return (
    <header className="app-header">
      <div className="brand-lockup">
        <span className="brand-mark" aria-hidden="true">
          <SearchCheck size={24} strokeWidth={2.2} />
        </span>
        <h1>Stock Sherlock</h1>
      </div>
      <NavigationTabs />
    </header>
  )
}
