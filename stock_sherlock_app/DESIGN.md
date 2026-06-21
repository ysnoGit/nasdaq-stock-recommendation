# Stock Sherlock Design Direction

## Purpose

Stock Sherlock should feel like a trustworthy financial analysis workspace: clean, modern, precise, and comfortable during repeated data-heavy screening tasks. The interface should prioritize comprehension and operational efficiency over marketing decoration.

The later UI implementation may use the [Coinbase Design.md reference](https://getdesign.md/coinbase/design-md) as general style inspiration. It must not copy Coinbase branding, logos, brand language, identity-specific colors, or proprietary interface content.

## Product Character

- **Clear:** Present hierarchy, labels, and states without visual noise.
- **Trustworthy:** Use restrained color, consistent spacing, explicit data states, and predictable interactions.
- **Finance-oriented:** Favor compact, scannable tables, controls, comparisons, and charts.
- **Modern:** Use crisp typography, deliberate whitespace, and subtle borders rather than decorative effects.
- **Polished:** Handle loading, empty, error, disabled, selected, and responsive states intentionally.

## Layout Principles

- Build the usable screening workspace as the primary screen rather than a marketing landing page.
- Keep navigation and controls stable so changing data does not shift the surrounding layout.
- Use full-width, unframed page regions with constrained inner content.
- Reserve cards for repeated records, modal content, or genuinely framed tools; avoid cards nested inside cards.
- Keep dense information organized with clear grouping, alignment, and whitespace.
- Design responsive behavior for desktop and mobile from the start, with no overlapping or clipped content.

## Visual Foundation

- Use a neutral light base with high-contrast text and a limited set of semantic accent colors.
- Avoid a one-note palette, decorative gradients, blurred shapes, and oversized rounded containers.
- Use typography sizes appropriate to the information density; dashboard headings should remain compact.
- Keep letter spacing at zero and avoid viewport-scaled font sizes.
- Use subtle borders and restrained elevation to distinguish interactive surfaces.
- Keep control and card corner radii at 8px or less unless a future design system establishes otherwise.

## Interaction Principles

- Use familiar controls: icons for standard tool actions, segmented controls for modes, toggles for binary settings, and menus for option sets.
- Pair unfamiliar icons with tooltips.
- Make focus, hover, active, disabled, loading, empty, and error states visible and accessible.
- Keep filtering and comparison workflows efficient for repeated use.
- Never perform heavy screening or raw-data processing in the browser.

## Data Presentation

- Tables should support scanning, comparison, stable column widths, and clear numeric alignment.
- Charts should communicate real financial data and include readable labels, units, time ranges, and empty states.
- Clearly distinguish user-selected parameters, calculated results, validation messages, and data freshness.
- Avoid implying precision or success when data is unavailable, incomplete, or stale.

## Accessibility

- Target WCAG 2.2 AA contrast and keyboard accessibility.
- Use semantic HTML before adding ARIA.
- Preserve visible focus indicators.
- Do not rely on color alone to communicate status.
- Respect reduced-motion preferences when motion is introduced.

## Deferred Decisions

The component system, icon package, chart library, date picker, detailed color tokens, type scale, responsive breakpoints, and final page composition will be chosen during UI implementation. This setup task does not establish the real application layout.
