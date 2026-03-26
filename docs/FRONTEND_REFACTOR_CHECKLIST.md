# Frontend Refactor Regression Checklist

This checklist defines feature-parity verification for the frontend modernization pass.

## Core Route Smoke Test

- `/` login landing renders and submits.
- `/dashboard` loads with no console errors.
- `/production` tabs and submit actions load.
- `/submissions` list renders and detail interactions work.
- `/purchase-orders` renders and detail modal opens.
- `/receiving` and `/shipping` views render and interactions respond.

## Dashboard Critical Flows

- Report type switch (`vendor`, `production`, `receive`) updates visible selectors.
- PO selector loads options and enables/disables report generation correctly.
- Receive selector lazy-loads options and report generation state updates.
- Generate report actions trigger expected behavior and user feedback.
- Recent submissions collapse/expand toggle works via keyboard and mouse.

## Modal and Row Interaction Flows

- Active receive row opens receive details.
- Recent submission row opens submission details.
- Ambiguous submission row opens resolution modal.
- Admin note badge opens note viewer without triggering row navigation.
- PO details modal open/close and nested navigation remain intact.

## Interaction Quality Gates

- No blocking `alert()` in refactored report-loading pathways.
- Loading and error states use shared notification patterns.
- Focus-visible styles are present on buttons, links, and inputs.
- No duplicate event listeners after repeated interactions.

## Final Acceptance Gates

- No broken links/buttons in touched templates.
- No JavaScript exceptions in browser console during core flows.
- Existing backend endpoints and payload contracts remain unchanged.
- Existing automated tests pass.
