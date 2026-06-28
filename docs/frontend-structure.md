# Frontend Structure

## Tech Stack

- **Framework**: React 19 + TypeScript
- **Build Tool**: Vite 6 (`@vitejs/plugin-react`)
- **Routing**: Custom pushState-based (no React Router)
- **Styling**: Single CSS file (~4273 lines, RTL-first)
- **State Management**: `useState` + `useMemo` + prop drilling (no Context/Redux/Zustand)
- **Icons**: `lucide-react`
- **Language**: Persian (RTL) UI, English for observability/debug
- **Real-time**: WebSocket with REST polling fallback

## Directory Layout

```
frontend/src/
├── main.tsx                        # React entry point (createRoot)
├── App.tsx                         # ~1137 lines — Shell, routing, data loading, all handlers
├── api.ts                          # ~796 lines — API client, types, trace system
├── constants.ts                    # Persian UI options (roles, payment methods, etc.)
├── styles.css                      # ~4273 lines — All styles (RTL + LTR sections)
├── types/
│   └── domain.ts                   # DomainType enum, SetupEntity interface
├── utils/
│   └── jalaliDate.ts               # Jalali/Persian calendar conversion utilities
├── pages/
│   ├── DashboardPage.tsx           # Project listing grid, search, create modal
│   ├── ProjectDetailPage.tsx       # ~1352 lines — Main project workspace (8 tabs)
│   ├── PeoplePage.tsx              # Person listing, detail drawer, profile editing
│   ├── ReportsPage.tsx             # Reports & CSV export with Persian date picker
│   └── AskYaraPage.tsx             # Legacy/deprecated AI input page
├── components/
│   ├── AiProcessingStatus.tsx      # Animated processing overlay (4-step progress)
│   ├── PersianDatePicker.tsx       # Jalali calendar popover
│   ├── TraceTimeline.tsx           # Event trace timeline viewer
│   └── TraceViewer.tsx             # Sidebar trace event list
├── ui/
│   ├── DomainUIController.tsx      # ~1300 lines — Routes interpretations to correct modal
│   ├── confirmPayload.ts           # Payload building and entity resolution helpers
│   ├── setup/
│   │   └── SetupModal.tsx          # Entity creation/registration form
│   ├── financial/
│   │   └── FinancialModal.tsx      # Financial transaction form
│   ├── entity/
│   │   └── EntityUpdateModal.tsx   # Profile field update form
│   └── split/
│       └── SplitFlowModal.tsx      # Two-step wizard (SETUP + FINANCIAL combined)
└── observability/
    ├── pages/
    │   ├── JobsPage.tsx            # Job listing table
    │   └── JobDetailPage.tsx       # Job detail with event timeline + detail panel
    ├── hooks/
    │   ├── useJobs.ts              # Job listing data hook
    │   ├── useNaturalInputJob.ts   # Job polling hook (1200ms interval)
    │   ├── useJobEventStream.ts    # WebSocket + REST fallback for job events
    │   └── useJobEvents.ts         # Composed hook (polling + stream)
    └── components/
        ├── JobTable.tsx            # Job list table
        ├── JobStatusBadge.tsx      # Colored status badge
        ├── JobProgressPanel.tsx    # Progress bar + milestone steps
        ├── EventTimeline.tsx       # Filterable event timeline
        ├── EventItem.tsx           # Timeline event dot + label
        └── EventDetailPanel.tsx    # Debug event inspector
```

## Pages Breakdown

### App.tsx (Shell)
- Handles all routing via `parseRoute()` (dashboard/project/people/jobs)
- Manages 27 `useState` variables for all application state
- Loads project data, workers, payments, work logs, invoices, history
- All CRUD operations, natural input submission, correction/void handlers
- Renders navigation sidebar + mobile bottom nav
- Contains `NotificationDropdown` for project alerts

### DashboardPage
- Grid of project cards with financial summary
- Search bar for filtering projects
- Create project modal
- Status badges (positive/negative/pending)

### ProjectDetailPage
- 8-tab navigation: Summary, People, Labor, Financial, Payables, Notes, Reports, Pending
- AI chat composer (text input with example chips)
- Summary metric cards (received, paid, net, debt, labor, pending, deferred)
- People grid grouped by role
- Work log groups per-worker with cards
- Transaction lists (payments, invoices)
- Person detail drawer
- Correction/Void modals for payments, work logs, payables, notes
- Pending interpretations list for user confirmation
- ReportsTab with PersianDatePicker + CSV export

### PeoplePage
- Role-based person grouping (CLIENT, DAILY_WORKER, SKILLED_WORKER, VENDOR, OTHER)
- Person detail cards with metric displays
- Detail drawer with profile editing form
- Payment and invoice lists per person

### ReportsPage
- Persian date picker with quick filters (week/month/year/all)
- Summary metric cards
- CSV export dropdown
- Worker report rows, payable report rows

## UI System

### Domain Modals (DomainUIController)
The `DomainUIController` is the central UI router for AI interpretations. Based on `interpretation.domain_route`, it renders one of:

| Domain Route | Modal | Purpose |
|-------------|-------|---------|
| SETUP | `SetupModal` | Create new worker/client/vendor |
| FINANCIAL | `FinancialModal` | Confirm payment/transaction |
| WORK | `WorkLogModal` | Confirm work log entry |
| ENTITY_UPDATE | `EntityUpdateModal` | Update phone/account/rate/notes |
| MIXED | `SplitFlowModal` | Two-step: entity info + financial |
| NOTE | Review card | Simple text note review |

### Shared UI Patterns
- **Modals**: All modals use a consistent `modal-shell` / `modal-header` / `modal-body` / `modal-footer` pattern
- **Cards**: Project cards, person cards, metric cards, work log cards
- **Buttons**: `primary-action` / `secondary-action` / `icon-button` styles
- **Badges**: Status badges (success/error/warning/info)

## Mobile vs Desktop Behavior

- **Desktop** (980px+): Full sidebar navigation, multi-column layouts
- **Tablet** (640-980px): Collapsed sidebar, adjusted grids
- **Mobile** (360-640px): Bottom navigation bar, single column, simplified modals
- **Observability section**: LTR layout regardless of device (English content)
- Responsive breakpoints at 980px, 640px, and 360px in CSS

## State Management

- All state lives in `App.tsx` (27 `useState` calls + `useRef`)
- Data flows down via props to child pages and components
- No Context API, no external state library
- `useMemo` for computed values (aggregated financials, filtered lists)
- `useEffect` for data loading on route/project changes
- Component callbacks (`onConfirm`, `onDiscard`, `onUpdateWorker`) for child-to-parent communication

## API Layer

- Singleton `api` object with generic `request<T>()` wrapper
- Trace correlation via `X-Trace-Id` header extraction from responses
- WebSocket subscription via `subscribeToTraceIds()` with deduplication
- Types defined inline in `api.ts` (40+ TypeScript interfaces)
