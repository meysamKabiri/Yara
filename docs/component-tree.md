# Component Tree

## Frontend Component Tree

```
App (App.tsx)
├── Navigation Sidebar
│   ├── NavIcon (home)
│   ├── NavIcon (users)
│   ├── NavIcon (activity)
│   └── NavIcon (chart)
├── NotificationDropdown
├── DashboardPage
│   ├── SearchBar
│   ├── ProjectCard[] (expandable with financial summary)
│   │   ├── StatusBadge
│   │   └── MetricRow (received/paid/net/debt)
│   ├── CreateProjectModal
│   └── EmptyState
├── ProjectDetailPage
│   ├── TabBar (summary | people | labor | financial | payables | notes | reports | pending)
│   ├── AI Chat Composer
│   │   ├── TextInput
│   │   ├── ExampleChips (5 Persian example inputs)
│   │   ├── SubmitButton
│   │   └── VoicePlaceholder / AttachPlaceholder
│   ├── Summary Tab
│   │   ├── FinancialSummaryCards (received, paid, net, debt, labor, pending, deferred)
│   │   └── MetricRow[]
│   ├── People Tab
│   │   ├── PersonCard[] (grouped by role)
│   │   │   ├── MetricDisplay (days worked, balance, payments)
│   │   │   └── RoleBadge
│   │   ├── PersonDetailDrawer
│   │   │   ├── ProfileEditForm (name, phone, account, rate, notes)
│   │   │   ├── PaymentList
│   │   │   └── InvoiceList
│   │   └── DetailList / DetailItem
│   ├── Labor Tab
│   │   ├── WorkLogGroupCard[] (per-worker grouping)
│   │   │   ├── WorkLogRow (task, unit, quantity, amount)
│   │   │   └── LaborStatsByWorker
│   │   └── TotalLaborDays / DailyWorkerPaidOut
│   ├── Financial Tab
│   │   ├── PaymentRow[] (with direction, method, amount)
│   │   └── CsvExportMenu
│   ├── Payables Tab
│   │   ├── PayableReportSection
│   │   └── PayableReportRow[]
│   ├── Notes Tab
│   │   └── HistoryEntry[]
│   ├── Reports Tab
│   │   ├── ProjectReportsTab
│   │   │   ├── PersianDatePicker
│   │   │   ├── QuickFilterButtons (week/month/year/all)
│   │   │   ├── SummaryMetricCards
│   │   │   ├── WorkerReportSection
│   │   │   │   └── WorkerReportRow[]
│   │   │   ├── PayableReportSection
│   │   │   │   └── PayableReportRow[]
│   │   │   └── CsvExportMenu
│   │   └── CsvExportDropdown
│   │       ├── "خلاصه پروژه" → summary.csv
│   │       ├── "پرداخت‌ها" → payments.csv
│   │       ├── "افراد" → people.csv
│   │       ├── "کارکرد کارگران" → work-logs.csv
│   │       ├── "بدهی‌ها و چک‌ها" → payables.csv
│   │       └── "یادداشت‌ها" → notes.csv
│   └── Pending Tab
│       ├── PendingInterpretationCard[]
│       └── DomainUIController (routes to correct modal)
│           ├── SetupModal (SETUP domain)
│           │   └── EditGrid: name, role, roleDetail, phone, accountNumber
│           ├── FinancialModal (FINANCIAL domain)
│           │   └── Form: entity selector, amount, direction, paymentMethod, dueDate
│           ├── EntityUpdateModal (ENTITY_UPDATE domain)
│           │   ├── CandidateList for NEEDS_SELECTION
│           │   ├── PersonSelector with create-new
│           │   └── Form: phone, account, dailyRate, notes
│           ├── SplitFlowModal (MIXED domain)
│           │   ├── Step 1: Entity info (name, role, phone, account)
│           │   └── Step 2: Financial transaction (entity, amount, direction)
│           └── WorkLogModal (WORK domain)
│               └── Work log entry with daily rate calculation
│   ├── CorrectionModal
│   │   └── CorrectionForm (field-specific)
│   ├── VoidModal
│   │   └── VoidReasonInput
│   └── ProjectEditModal
│       └── ProjectNameField + DescriptionField
├── PeoplePage
│   ├── PersonGroup[] (by role)
│   ├── PersonCard[]
│   │   ├── MetricDisplay
│   │   └── RoleBadge
│   ├── PersonDetailDrawer
│   │   ├── ProfileEditForm
│   │   ├── PaymentList
│   │   └── InvoiceList
│   └── DetailList / DetailItem / PaymentList / InvoiceList
├── ReportsPage
│   ├── PersianDatePicker
│   ├── QuickFilterButtons
│   ├── SummaryMetricCards
│   ├── CsvExportMenu
│   ├── WorkerReportRows
│   └── PayableReportRows
├── JobsPage (observability)
│   └── JobTable
│       └── JobStatusBadge
├── JobDetailPage (observability)
│   ├── JobDetailHeader
│   ├── SummaryGrid (trace_id, events, latency)
│   ├── EventTimeline
│   │   ├── FilterTabs (ALL/ERROR/LLM/EXECUTION)
│   │   └── EventItem[] (timeline dots + labels)
│   ├── EventDetailPanel (metadata + JSON viewer)
│   └── TraceTimeline
├── AiProcessingStatus (overlay)
│   ├── 4-Step Animated Progress
│   ├── StepIndicator (pending/current/done)
│   ├── ProgressBar
│   └── ErrorBlock with Retry
├── PersianDatePicker
│   └── JalaliCalendarPopover
│       ├── MonthNavigation
│       ├── WeekdayHeaders
│       └── DayGrid
├── TraceTimeline
│   └── TraceEventGroup[] (JOB, DOMAIN_ROUTER, LLM, EXECUTION_ENGINE, DB)
└── TraceViewer
    └── TraceEventList (sidebar)
```

## Backend Component Tree

```
FastAPI App (main.py:63)
│
├── API Layer (routers)
│   ├── health.py
│   │   └── GET /health (DB, Redis, Ollama)
│   ├── projects.py (~4746 lines)
│   │   ├── GET/POST /projects
│   │   ├── GET/PATCH /projects/{id}
│   │   ├── GET/POST /projects/{id}/workers
│   │   ├── GET/POST /projects/{id}/work-logs
│   │   ├── GET/POST /projects/{id}/payments
│   │   ├── GET/POST /projects/{id}/invoices
│   │   ├── POST /projects/{id}/natural-input
│   │   ├── GET/PATCH/DELETE /pending-interpretations/{id}
│   │   ├── GET/POST /projects/{id}/raw-entries
│   │   ├── GET /projects/{id}/history
│   │   ├── GET /projects/{id}/operating-summary
│   │   ├── GET /projects/{id}/reports/summary
│   │   ├── PATCH /projects/{id}/payments/{id}  (correction)
│   │   ├── POST /projects/{id}/payments/{id}/void
│   │   ├── PATCH /projects/{id}/work-logs/{id}  (correction)
│   │   ├── POST /projects/{id}/work-logs/{id}/void
│   │   ├── PATCH /projects/{id}/payables/{id}   (correction)
│   │   ├── POST /projects/{id}/payables/{id}/void
│   │   ├── PATCH /projects/{id}/notes/{id}      (correction)
│   │   └── POST /projects/{id}/notes/{id}/void
│   ├── job_websockets.py
│   │   └── WS /ws/jobs/{job_id}
│   ├── traces.py
│   │   └── GET /traces/{id}
│   ├── shadow_analytics.py
│   │   └── GET /shadow-analytics
│   ├── shadow_migration.py
│   │   └── GET /shadow-migration
│   ├── financial_migration.py
│   │   └── GET /financial-migration/status
│   ├── metrics.py
│   │   └── GET /metrics
│   └── sandbox.py
│       └── POST /sandbox/seed
│
├── Services Layer
│   ├── LLM Pipeline
│   │   ├── llm_v2_interpreter.py (Ollama-based interpretation)
│   │   ├── llm_v2_validator.py (output validation)
│   │   └── llm_extraction.py (legacy extraction)
│   ├── Domain Processing
│   │   ├── domain_router_service.py (domain routing)
│   │   ├── entity_resolution_service.py (entity matching)
│   │   ├── entity_registry.py (SETUP execution)
│   │   └── entity_normalizer.py (name normalization)
│   ├── Financial
│   │   ├── execution_engine.py (confirmed write authority)
│   │   ├── financial_summary.py (operating summaries)
│   │   ├── persian_money_engine.py (Persian number parsing)
│   │   ├── persian_project_payment.py (payment detection)
│   │   └── persian_role_extractor.py (role phrase mapping)
│   ├── Migration
│   │   ├── financial_migration_gate.py (safety gate)
│   │   ├── financial_migration_logger.py (decision logging)
│   │   ├── compare_legacy_vs_shadow.py (diff engine)
│   │   ├── shadow_analytics_service.py (analytics aggregation)
│   │   ├── shadow_migration_decision_engine.py (readiness scoring)
│   │   ├── shadow_conflict_analyzer.py (conflict classification)
│   │   └── shadow_logger.py (shadow comparison storage)
│   └── Reporting
│       ├── reporting_service.py (CSV/PDF report generation)
│       └── execution_comparator.py (execution audit)
│
├── Core Layer
│   ├── unified_pipeline.py (~2415 lines)
│   │   └── process_input() — central orchestrator
│   │       ├── _split_multi_event_text()
│   │       ├── _process_legacy_path() (semantic rules)
│   │       ├── _process_llm_path() (LLM v2 interpreter)
│   │       ├── _apply_governance() (legacy vs llm decision)
│   │       ├── _route_domains() (domain routing)
│   │       └── _emit_observability_events()
│   ├── config.py (env settings)
│   ├── queue.py (Redis + RQ)
│   ├── trace_context.py (ContextVar propagation)
│   ├── event_tracker.py (TraceEvent writer)
│   ├── feature_flags.py (migration mode flags)
│   ├── llm_cache.py (in-memory LRU cache)
│   ├── llm_authority_controller.py (alt migration controller)
│   ├── financial_role_repair.py (migration role repair)
│   ├── observability_schema.py (trace models)
│   ├── observability_service.py (trace recording)
│   ├── observability_validator.py (trace integrity)
│   ├── governance/
│   │   ├── governance_context_builder.py
│   │   └── unified_governance_engine.py
│   ├── observability/
│   │   ├── decision_logger.py (audit trail)
│   │   └── performance_logger.py (metrics)
│   ├── runtime/
│   │   └── request_cache.py (per-request cache)
│   ├── semantic_rules/
│   │   ├── semantic_rule_engine.py (~650 lines)
│   │   ├── conflict_detector.py
│   │   └── explainability.py
│   └── validation/
│       └── financial_validator.py
│
├── Database Layer
│   ├── models/core.py (16 ORM models)
│   ├── db/base.py (Base + mixins)
│   ├── db/session.py (session factory)
│   └── alembic/ (25 migrations)
│
├── Worker Layer
│   ├── jobs/natural_input_job.py (RQ job function)
│   ├── core/queue.py (queue config, Redis)
│   └── scripts/start_worker.py (worker entry point)
│
└── Dev Tools
    ├── dev_tools/semantic_firewall/
    │   ├── firewall.py
    │   ├── run_semantic_tests.py
    │   └── test_cases.py
    ├── dev_tools/sandbox/
    │   ├── scenarios.py
    │   ├── generator.py
    │   ├── reset_db.py
    │   └── seed_runner.py
    └── dev_cli.py (Click CLI)
```
