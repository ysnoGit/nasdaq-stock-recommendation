import { SlidersHorizontal } from 'lucide-react'

export function NavigationTabs() {
  return (
    <nav className="navigation-tabs" aria-label="Primary navigation">
      <button className="navigation-tab" type="button" aria-current="page">
        <SlidersHorizontal aria-hidden="true" size={16} strokeWidth={2} />
        Stock Filter
      </button>
    </nav>
  )
}
