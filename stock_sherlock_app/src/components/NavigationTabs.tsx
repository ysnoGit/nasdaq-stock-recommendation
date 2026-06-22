import { BookOpen, SlidersHorizontal } from 'lucide-react'

export type AppPage = 'guide' | 'filter'

type NavigationTabsProps = {
  activePage: AppPage
  onNavigate: (page: AppPage) => void
}

export function NavigationTabs({ activePage, onNavigate }: NavigationTabsProps) {
  return (
    <nav className="navigation-tabs" aria-label="Primary navigation">
      <button
        className={`navigation-tab ${activePage === 'guide' ? 'navigation-tab-active' : ''}`}
        type="button"
        aria-current={activePage === 'guide' ? 'page' : undefined}
        onClick={() => onNavigate('guide')}
      >
        <BookOpen aria-hidden="true" size={16} strokeWidth={2} />
        How It Works
      </button>
      <button
        className={`navigation-tab ${activePage === 'filter' ? 'navigation-tab-active' : ''}`}
        type="button"
        aria-current={activePage === 'filter' ? 'page' : undefined}
        onClick={() => onNavigate('filter')}
      >
        <SlidersHorizontal aria-hidden="true" size={16} strokeWidth={2} />
        Stock Filter
      </button>
    </nav>
  )
}
