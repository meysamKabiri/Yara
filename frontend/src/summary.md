# Refactoring: Domain-Driven UI Components

## Goal
Replace the unified modal system with strict domain-driven UI components, routing based on backend `domain_router` output (SETUP, FINANCIAL, ENTITY_UPDATE, MIXED).

## Done
- Created `types/domain.ts` — `DomainType` + shared `SetupEntity` type.
- Created `ui/setup/SetupModal.tsx` — fields: name, role, phone, account_number, project (read-only).
- Created `ui/financial/FinancialModal.tsx` — fields: entity_id, amount, direction, payment_method, project_id.
- Created `ui/entity/EntityUpdateModal.tsx` — fields: name, phone, account_number, role, role_detail.
- Created `ui/split/SplitFlowModal.tsx` — two-step wizard (setup step, financial step).
- Created `ui/DomainUIController.tsx` — orchestrates entity resolution pre-step + domain switch.
- Updated `api.ts` — added `ENTITY_UPDATE` to domain type union.
- Refactored `App.tsx`:
  - Added direct confirm functions (`confirmSetupEntities`, `confirmFinancialTransaction`, `confirmMixedInterpretation`, `confirmEntityUpdateAction`).
  - Replaced inline unified modal (~250 lines) with `<DomainUIController />`.
  - Removed all unused helper functions (~25 functions removed).
  - Removed unused state (`editingId`, `editForm`, `setEditingId`, `setEditForm`).
  - Removed unused props passed to DomainUIController (`editingId`, `editForm`, `setEditingId`, `setEditForm`, `onStartEdit`, `onSaveEdit`, `onConfirmEdited`).
  - Fixed `setupEditEntities` state type to use shared `SetupEntity[]`.
- Consolidated `SetupEntity` type into `types/domain.ts` — imported by App.tsx, DomainUIController, and SetupModal (fixes type incompatibility).
- TypeScript compiles cleanly (`tsc --noEmit` = zero errors).

## Key Decisions
- Each domain modal manages its own local state.
- Entity resolution pre-step remains in DomainUIController using old confirm functions.
- MIXED domain uses `confirmMixedInterpretation` with combined setup + financial payload.
