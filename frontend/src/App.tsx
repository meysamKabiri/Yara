import { FormEvent, useEffect, useMemo, useState } from "react";
import { BarChart3, Bell, Home, Users } from "lucide-react";
import {
  api,
  HistoryEntry,
  Invoice,
  OperatingSummary,
  Payment,
  PaymentType,
  PendingInterpretation,
  Project,
  ProjectDetail,
  RawEntry,
  Worker,
  WorkerState,
  WorkLog,
} from "./api";
import { DashboardPage } from "./pages/DashboardPage";
import { PeoplePage } from "./pages/PeoplePage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ReportsPage } from "./pages/ReportsPage";

const exampleInputs = [
  "کارفرمای پروژه میثم کبیری است",
  "مش رحیم امروز کار کرد",
  "نادری جوشکار امروز جوشکاری کرد",
  "۱۰۰ میلیون دادم به جوشکار",
  "میثم ۲۰۰ میلیون پول داد",
];

type Route =
  | { name: "dashboard" }
  | { name: "project"; projectId: number | null }
  | { name: "people" }
  | { name: "person"; personId: number }
  | { name: "reports" };

function parseRoute(pathname: string): Route {
  const projectMatch = pathname.match(/^\/projects\/(\d+)/);
  const personMatch = pathname.match(/^\/people\/(\d+)/);
  if (projectMatch) return { name: "project", projectId: Number(projectMatch[1]) };
  if (personMatch) return { name: "person", personId: Number(personMatch[1]) };
  if (pathname === "/people") return { name: "people" };
  if (pathname === "/reports") return { name: "reports" };
  return { name: "dashboard" };
}

function NavIcon({ name }: { name: string }) {
  if (name === "home") return <Home aria-hidden="true" size={19} />;
  if (name === "users") return <Users aria-hidden="true" size={19} />;
  return <BarChart3 aria-hidden="true" size={19} />;
}

type ProjectCardFinancials = {
  received: number;
  paid: number;
  net: number;
  debt: number;
};

function friendlyError(err: unknown): string {
  if (!(err instanceof Error)) return "خطایی رخ داد. دوباره تلاش کنید.";
  try {
    const parsed = JSON.parse(err.message) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch {
    return err.message || "خطایی رخ داد. دوباره تلاش کنید.";
  }
  return err.message || "خطایی رخ داد. دوباره تلاش کنید.";
}

function formatMoney(value: string | null): string | null {
  if (!value) return null;
  return `${Number(value).toLocaleString("fa-IR")} تومان`;
}

function firstEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  return interpretation.extracted_entities?.[0] ?? {};
}

function workUnitFromInterpretation(interpretation: PendingInterpretation): string {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  const work = si?.work as Record<string, unknown> | undefined;
  return typeof work?.unit === "string" ? work.unit : "";
}

function entityName(interpretation: PendingInterpretation): string {
  const entity = firstEntity(interpretation);
  return typeof entity.name === "string" && entity.name.trim() ? entity.name.trim() : "نامشخص";
}

function isUnknownEntity(interpretation: PendingInterpretation): boolean {
  const name = entityName(interpretation);
  return name === "نامشخص" || name === "طرف حساب نامشخص" || name === "ناشناس" || name.toLowerCase() === "unknown";
}

function hasExplicitCreateNew(interpretation: PendingInterpretation): boolean {
  return firstEntity(interpretation).create_new === true;
}

function structuredConfidence(interpretation: PendingInterpretation): number {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  const value = interpretation.confidence ?? si?.confidence ?? 0;
  return Number(value || 0);
}

function isAmbiguousInterpretation(interpretation: PendingInterpretation): boolean {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  return si?.ambiguity === true;
}

function allowsVendorAutoCreate(interpretation: PendingInterpretation): boolean {
  const entity = firstEntity(interpretation);
  return (
    interpretation.canonical_event_type === "FINANCIAL_EVENT"
    && preferredEntityType(interpretation) === "VENDOR"
    && typeof entity.name === "string"
    && entity.name.trim().length > 0
    && !interpretation.suggested_entity_id
    && !isUnknownEntity(interpretation)
    && !isAmbiguousInterpretation(interpretation)
    && structuredConfidence(interpretation) >= 0.85
  );
}

function needsFinancialEntityResolution(interpretation: PendingInterpretation): boolean {
  return interpretation.canonical_event_type === "FINANCIAL_EVENT" && !interpretation.suggested_entity_id && !hasExplicitCreateNew(interpretation) && !allowsVendorAutoCreate(interpretation);
}

function unsafeFinancialReason(interpretation: PendingInterpretation): string | null {
  if (interpretation.canonical_event_type !== "FINANCIAL_EVENT") return null;
  if (!interpretation.suggested_entity_id && !hasExplicitCreateNew(interpretation) && !allowsVendorAutoCreate(interpretation)) return "طرف حساب باید مشخص شود.";
  if (!interpretation.extracted_amount) return "مبلغ باید مشخص شود.";
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  const financial = si?.financial as Record<string, unknown> | undefined;
  const structuredDirection = financial?.direction;
  if (!interpretation.financial_direction && (!structuredDirection || structuredDirection === "NONE")) return "جهت مالی باید مشخص شود.";
  return null;
}

function roleLabelFromType(type: string | undefined): string {
  if (type === "CLIENT") return "کارفرما";
  if (type === "VENDOR") return "فروشنده";
  if (type === "SKILLED_WORKER") return "استادکار";
  if (type === "DAILY_WORKER") return "کارگر ساده";
  return "فرد پروژه";
}

function setupEntities(interpretation: PendingInterpretation): Array<{ name: string; type: string; roleDetail: string | null; phone: string | null; accountNumber: string | null; dailyRate: string | null }> {
  return (interpretation.extracted_entities ?? [])
    .map((entity) => ({
      name: typeof entity.name === "string" ? entity.name : "",
      type: entityTypeFromRecord(entity),
      roleDetail: typeof entity.role_detail === "string" && entity.role_detail.trim() ? entity.role_detail.trim() : null,
      phone: typeof entity.phone === "string" && entity.phone.trim() ? entity.phone.trim() : null,
      accountNumber: typeof entity.account_number === "string" && entity.account_number.trim() ? entity.account_number.trim() : null,
      dailyRate: typeof entity.daily_rate === "string" || typeof entity.daily_rate === "number" ? String(entity.daily_rate) : null,
    }))
    .filter((entity) => entity.name.trim());
}

function setupRoleLabel(type: string): string {
  return roleLabelFromType(type);
}

function entityTypeFromRecord(entity: Record<string, unknown>): string {
  const projectRole = typeof entity.project_role === "string" ? entity.project_role : undefined;
  const type = typeof entity.type === "string" ? entity.type : undefined;
  const roleGuess = typeof entity.role_guess === "string" ? entity.role_guess : undefined;
  const candidate = projectRole ?? type ?? roleGuess;
  if (candidate === "CLIENT") return "CLIENT";
  if (candidate === "VENDOR") return "VENDOR";
  if (candidate === "SKILLED" || candidate === "SKILLED_WORKER") return "SKILLED_WORKER";
  if (candidate === "DAILY_WORKER" || candidate === "WORKER") return "DAILY_WORKER";
  return "OTHER";
}

function preferredEntityType(interpretation: PendingInterpretation): string {
  return entityTypeFromRecord(firstEntity(interpretation));
}

function unresolvedEntityTitle(interpretation: PendingInterpretation): string {
  const name = entityName(interpretation);
  const role = setupRoleLabel(preferredEntityType(interpretation));
  if (name === "نامشخص" || name === "طرف حساب نامشخص") return "طرف حساب در پروژه پیدا نشد.";
  return `${role} «${name}» در پروژه پیدا نشد.`;
}

function unresolvedEntityHelp(interpretation: PendingInterpretation): string {
  const role = setupRoleLabel(preferredEntityType(interpretation));
  return `یک ${role} موجود را انتخاب کنید یا ${role} جدید ایجاد کنید.`;
}

function isUnresolvedVendorAutoCreate(interpretation: PendingInterpretation): boolean {
  return allowsVendorAutoCreate(interpretation);
}

function StructuredDetails({ interpretation }: { interpretation: PendingInterpretation }) {
  const [showDetails, setShowDetails] = useState(false);
  return (
    <section className="approval-section">
      <button className="text-button" type="button" onClick={() => setShowDetails(!showDetails)}>
        {showDetails ? "پنهان کردن جزئیات فنی" : "نمایش جزئیات فنی برداشت LLM"}
      </button>
      {showDetails && (
        <dl className="approval-fields technical-details">
          {structuredInterpretationRows(interpretation).map((row) => <div key={`si-${row.label}`}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
        </dl>
      )}
    </section>
  );
}

function resolvedWorker(interpretation: PendingInterpretation, workers: Worker[]): Worker | undefined {
  const name = entityName(interpretation);
  return workers.find((worker) => worker.name === name);
}

function financialDirection(interpretation: PendingInterpretation, workers: Worker[]): "incoming" | "outgoing" | "debt" {
  if (interpretation.financial_direction === "INCOMING") return "incoming";
  if (interpretation.financial_direction === "DEBT") return "debt";
  if (["INVOICE", "DEBT_CREATED"].includes(interpretation.semantic_action)) return "debt";
  const entity = firstEntity(interpretation);
  const type = resolvedWorker(interpretation, workers)?.type ?? (typeof entity.type === "string" ? entity.type : typeof entity.role_guess === "string" ? entity.role_guess : undefined);
  return type === "CLIENT" ? "incoming" : "outgoing";
}

function actionSummary(interpretation: PendingInterpretation, workers: Worker[]): string {
  if (interpretation.semantic_action === "PURCHASE_PAID") return "خرید پرداخت‌شده";
  if (interpretation.semantic_action === "DEBT_CREATED" || interpretation.semantic_action === "INVOICE") return "خرید نسیه / بدهی فروشنده";
  if (interpretation.semantic_action === "CHECK_PAYMENT" || interpretation.semantic_action === "DEFERRED_PAYMENT") return "پرداخت چکی یا مدت‌دار";
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") return financialDirection(interpretation, workers) === "incoming" ? "دریافت پول برای پروژه" : "پرداخت از پروژه";
  if (interpretation.canonical_event_type === "WORK_EVENT") return "ثبت کارکرد";
  if (interpretation.canonical_event_type === "SETUP_EVENT") return "ثبت فرد پروژه";
  return "یادداشت پروژه";
}

function approvalCategory(interpretation: PendingInterpretation): string {
  if (interpretation.canonical_event_type === "SETUP_EVENT") return "افزودن فرد به پروژه";
  return "برداشت یارا";
}

function counterpartyLabel(interpretation: PendingInterpretation, workers: Worker[]): string {
  const direction = financialDirection(interpretation, workers);
  const type = preferredEntityType(interpretation);
  if (direction === "incoming" || type === "CLIENT") return "کارفرما";
  if (direction === "debt" || type === "VENDOR" || interpretation.semantic_action === "PURCHASE_PAID") return "فروشنده";
  if (type === "SKILLED_WORKER") return "استادکار";
  if (type === "DAILY_WORKER") return "کارگر";
  return "فرد";
}

function structuredInterpretationRows(interpretation: PendingInterpretation): Array<{ label: string; value: string }> {
  const raw = interpretation.structured_interpretation;
  if (!raw) return [];
  const si = raw as Record<string, unknown>;
  const rows: Array<{ label: string; value: string }> = [
    { label: "نیت (intent)", value: String(si.intent ?? "") },
    { label: "عملیات (action)", value: String(si.action ?? "") },
  ];
  const entities = si.entities;
  if (Array.isArray(entities) && entities.length) {
    const entityText = entities
      .map((e: Record<string, unknown>) => `${e.name ?? ""} - ${e.project_role ?? ""}${e.role_detail ? ` (${e.role_detail})` : ""}`)
      .join(" | ");
    rows.push({ label: "طرف‌حساب (entities)", value: entityText });
  }
  const financial = si.financial as Record<string, unknown> | undefined;
  if (financial?.amount != null) {
    rows.push({ label: "مبلغ (amount)", value: String(financial.amount) });
    rows.push({ label: "جهت (direction)", value: String(financial.direction) });
  }
  const work = si.work as Record<string, unknown> | undefined;
  if (work?.quantity != null) {
    rows.push({ label: "مقدار کار", value: `${work.quantity}${work.unit ? ` ${work.unit}` : ""}` });
  }
  rows.push({ label: "اطمینان", value: String(Math.round(Number(si.confidence ?? 0) * 100)) + "%" });
  if (si.reasoning_summary) {
    rows.push({ label: "توضیح", value: String(si.reasoning_summary) });
  }
  return rows;
}

function understoodRows(interpretation: PendingInterpretation, workers: Worker[]): Array<{ label: string; value: string }> {
  const entity = entityName(interpretation);
  const amount = formatMoney(interpretation.extracted_amount);
  if (interpretation.canonical_event_type === "SETUP_EVENT") {
    const entities = setupEntities(interpretation);
    if (entities.length > 1) {
      return [{ label: "افراد", value: entities.map((item) => `${item.name} - ${setupRoleLabel(item.type)}`).join("\n") }];
    }
    const setupEntity = entities[0];
    const role = setupRoleLabel(setupEntity?.type ?? "OTHER");
    return [
      { label: "نقش", value: role },
      { label: "نام", value: entity },
      ...(setupEntity?.type === "SKILLED_WORKER" && setupEntity.roleDetail ? [{ label: "تخصص", value: setupEntity.roleDetail }] : []),
    ];
  }
  if (interpretation.canonical_event_type === "WORK_EVENT") {
    const entityType = resolvedWorker(interpretation, workers)?.type ?? (typeof firstEntity(interpretation).type === "string" ? firstEntity(interpretation).type : undefined);
    return [
      { label: "نقش", value: roleLabelFromType(entityType === "SKILLED_WORKER" ? "SKILLED_WORKER" : "DAILY_WORKER") },
      { label: entityType === "SKILLED_WORKER" ? "استادکار" : "کارگر", value: entity },
      { label: "عملیات", value: "ثبت کارکرد" },
      { label: "مقدار", value: interpretation.extracted_quantity ?? "1" },
    ];
  }
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") {
    if (interpretation.semantic_action === "PURCHASE_PAID") {
      return [
        { label: "عملیات", value: "خرید پرداخت‌شده" },
        { label: "مبلغ", value: amount ?? "مبلغ نامشخص" },
        { label: "فروشنده", value: entity },
        ...(interpretation.due_date ? [{ label: "تاریخ سررسید", value: interpretation.due_date }] : []),
      ];
    }
    if (interpretation.semantic_action === "DEBT_CREATED" || interpretation.semantic_action === "INVOICE") {
      return [
        { label: "عملیات", value: "خرید نسیه / بدهی فروشنده" },
        { label: "مبلغ", value: amount ?? "مبلغ نامشخص" },
        { label: "فروشنده", value: entity },
        ...(interpretation.due_date ? [{ label: "تاریخ سررسید", value: interpretation.due_date }] : []),
      ];
    }
    if (financialDirection(interpretation, workers) === "incoming") {
      return [
        { label: "عملیات", value: "دریافت از کارفرما" },
        { label: "مبلغ", value: amount ?? "مبلغ نامشخص" },
        { label: "کارفرما", value: entity },
      ];
    }
    return [
      { label: "عملیات", value: actionSummary(interpretation, workers) },
      { label: "مبلغ", value: amount ?? "مبلغ نامشخص" },
      { label: counterpartyLabel(interpretation, workers), value: entity },
      ...(interpretation.due_date ? [{ label: "تاریخ سررسید", value: interpretation.due_date }] : []),
    ];
  }
  return [{ label: "یادداشت", value: interpretation.description || interpretation.raw_input_text }];
}

function outcomeSummary(interpretation: PendingInterpretation, workers: Worker[]): string[] {
  const entity = entityName(interpretation);
  const amount = formatMoney(interpretation.extracted_amount);
  if (interpretation.canonical_event_type === "SETUP_EVENT") {
    const entities = setupEntities(interpretation);
    if (entities.length > 1) return [`${entities.length} نفر به این پروژه اضافه می‌شوند.`];
    const setupEntity = entities[0];
    const role = setupRoleLabel(setupEntity?.type ?? "OTHER");
    const specialty = setupEntity?.type === "SKILLED_WORKER" && setupEntity.roleDetail ? ` ${setupEntity.roleDetail}` : "";
    return [`${entity} به عنوان ${role}${specialty} به پروژه اضافه می‌شود.`];
  }
  if (interpretation.canonical_event_type === "WORK_EVENT") return [`${interpretation.extracted_quantity ?? "۱"} واحد کار برای ${entity} ثبت می‌شود.`];
  if (interpretation.semantic_action === "DEBT_CREATED" || interpretation.semantic_action === "INVOICE") return [`یارا ثبت می‌کند که از ${entity}${amount ? ` به مبلغ ${amount}` : ""} خرید نسیه انجام شده و بدهی فروشنده باز است.`];
  if (interpretation.semantic_action === "PURCHASE_PAID") return [`یارا ثبت می‌کند که از ${entity} به مبلغ ${amount ?? "نامشخص"} خرید انجام شده و پرداخت شده است.`];
  if (isUnresolvedVendorAutoCreate(interpretation)) return [`فروشنده «${entity}» ایجاد می‌شود و خرید${amount ? ` به مبلغ ${amount}` : ""} ثبت می‌شود.`];
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") {
    if (financialDirection(interpretation, workers) === "incoming") return [`یارا ثبت می‌کند که ${entity} مبلغ ${amount ?? "نامشخص"} به پروژه پرداخت کرده است.`];
    return [`یارا ثبت می‌کند که پروژه مبلغ ${amount ?? "نامشخص"} به ${entity} پرداخت کرده است.`];
  }
  return ["یک یادداشت در تاریخچه پروژه ذخیره می‌شود."];
}

function ambiguousEntityCandidates(interpretation: PendingInterpretation, workers: Worker[]): Worker[] {
  const name = entityName(interpretation);
  if (name === "نامشخص" || name.length < 2) return [];
  const exact = workers.filter((worker) => worker.name === name);
  if (exact.length === 1) return [];
  return workers.filter((worker) => worker.name.includes(name));
}

function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectName, setProjectName] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [rawEntries, setRawEntries] = useState<RawEntry[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [workerStates, setWorkerStates] = useState<WorkerState[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [workLogs, setWorkLogs] = useState<WorkLog[]>([]);
  const [operatingSummary, setOperatingSummary] = useState<OperatingSummary | null>(null);
  const [projectFinancials, setProjectFinancials] = useState<Record<number, ProjectCardFinancials>>({});
  const [naturalText, setNaturalText] = useState("");
  const [pendingInterpretations, setPendingInterpretations] = useState<PendingInterpretation[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<Record<string, string>>({});
  const [setupEditEntities, setSetupEditEntities] = useState<Record<number, Array<{ name: string; type: string; roleDetail?: string | null; phone?: string | null; accountNumber?: string | null; dailyRate?: string | null }>>>({});
  const [ambiguitySelections, setAmbiguitySelections] = useState<Record<number, number>>({});
  const [unknownEntityForms, setUnknownEntityForms] = useState<Record<number, { workerId: string; name: string; type: string }>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const isLoading = loadingAction !== null;
  const routeProjectId = route.name === "project" ? route.projectId : null;
  const activeProjectId = routeProjectId ?? selectedProjectId ?? projects[0]?.id ?? null;
  const openDebtCount = Object.values(projectFinancials).filter((item) => item.debt > 0).length;

  const navItems = useMemo(
    () => [
      { label: "خانه", path: "/dashboard", active: route.name === "dashboard" || route.name === "project", icon: "home" },
      { label: "افراد", path: "/people", active: route.name === "people" || route.name === "person", icon: "users" },
      { label: "گزارش‌ها", path: "/reports", active: route.name === "reports", icon: "reports" },
    ],
    [route.name],
  );

  useEffect(() => {
    function handlePopState() {
      setRoute(parseRoute(window.location.pathname));
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    if (window.location.pathname === "/") navigate("/dashboard", true);
    loadProjects();
  }, []);

  useEffect(() => {
    if (!selectedProjectId && projects.length > 0) setSelectedProjectId(projects[0].id);
    if (projects.length > 0) loadProjectFinancials(projects);
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (routeProjectId && routeProjectId !== selectedProjectId) setSelectedProjectId(routeProjectId);
  }, [routeProjectId, selectedProjectId]);

  useEffect(() => {
    if (activeProjectId) loadProjectData(activeProjectId);
  }, [activeProjectId]);

  function navigate(path: string, replace = false) {
    if (replace) window.history.replaceState({}, "", path);
    else window.history.pushState({}, "", path);
    setRoute(parseRoute(path));
  }

  async function runAction(label: string, action: () => Promise<void>) {
    setLoadingAction(label);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setLoadingAction(null);
    }
  }

  async function loadProjects() {
    await runAction("در حال بارگذاری پروژه‌ها", async () => setProjects(await api.listProjects()));
  }

  async function loadProjectFinancials(projectList: Project[]) {
    try {
      const entries = await Promise.all(
        projectList.map(async (project) => {
          const [projectPayments, summary] = await Promise.all([
            api.listPayments(project.id),
            api.getOperatingSummary(project.id),
          ]);
          const received = Number(summary.total_received_from_client ?? summary.total_received ?? 0);
          const paid = Number(summary.total_paid_out ?? 0);
          const debt = Number(summary.open_payables ?? 0);
          return [project.id, { received, paid, debt, net: Number(summary.project_balance ?? received - paid - debt) }] as const;
        }),
      );
      setProjectFinancials(Object.fromEntries(entries));
    } catch (err) {
      setError(friendlyError(err));
    }
  }

  async function loadProjectData(projectId: number) {
    await runAction("در حال بارگذاری پروژه", async () => {
      const [detail, rawEntryList, workerList, states, historyList, invoiceList, paymentList, workLogList, summary] = await Promise.all([
        api.getProject(projectId),
        api.listRawEntries(projectId),
        api.listWorkers(projectId),
        api.listWorkerStates(projectId),
        api.listHistory(projectId),
        api.listInvoices(projectId),
        api.listPayments(projectId),
        api.listWorkLogs(projectId),
        api.getOperatingSummary(projectId),
      ]);
      setProjectDetail(detail);
      setRawEntries(rawEntryList);
      setWorkers(workerList);
      setWorkerStates(states);
      setHistory(historyList);
      setInvoices(invoiceList);
      setPayments(paymentList);
      setWorkLogs(workLogList);
      setOperatingSummary(summary);
    });
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    const name = projectName.trim();
    if (!name) return;
    await runAction("در حال ایجاد پروژه", async () => {
      const project = await api.createProject(name);
      setProjectName("");
      setProjects(await api.listProjects());
      setSelectedProjectId(project.id);
    });
  }

  async function submitNaturalInput(event: FormEvent) {
    event.preventDefault();
    if (!activeProjectId || !naturalText.trim()) return;
    const submittedText = naturalText.trim();
    await runAction("در حال پردازش ورودی", async () => {
      setSuccessMessage(null);
      const result = await api.processNaturalInput(activeProjectId, submittedText);
      setPendingInterpretations(result.interpretations);
      setNaturalText("");
    });
  }

  function openProject(projectId: number) {
    setSelectedProjectId(projectId);
    navigate(`/projects/${projectId}`);
  }

  function startEdit(interpretation: PendingInterpretation) {
    const entity = firstEntity(interpretation);
    setEditingId(interpretation.id);
    if (interpretation.canonical_event_type === "SETUP_EVENT") {
      setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: setupEntities(interpretation) });
    }
    setEditForm({
      entity: typeof entity.name === "string" ? entity.name : "",
      entityType: typeof entity.type === "string" ? entity.type : typeof entity.role_guess === "string" ? entity.role_guess : "DAILY_WORKER",
      canonical_event_type: interpretation.canonical_event_type,
      semantic_action: interpretation.semantic_action,
      extracted_amount: interpretation.extracted_amount ?? "",
      extracted_quantity: interpretation.extracted_quantity ?? "",
      unit: workUnitFromInterpretation(interpretation),
      payment_method: interpretation.payment_method ?? "",
      due_date: interpretation.due_date ?? "",
      description: interpretation.description ?? "",
    });
  }

  async function saveEdit(interpretation: PendingInterpretation) {
    await runAction("در حال ذخیره برداشت", async () => {
      const currentWork = (interpretation.structured_interpretation?.work ?? {}) as Record<string, unknown>;
      const structuredInterpretation = interpretation.structured_interpretation
        ? {
          ...interpretation.structured_interpretation,
          work: {
            ...currentWork,
            quantity: editForm.extracted_quantity || currentWork.quantity || null,
            unit: editForm.unit || currentWork.unit || null,
            description: editForm.description || currentWork.description || null,
          },
        }
        : null;
      const updated = await api.updatePendingInterpretation(interpretation.id, {
        canonical_event_type: editForm.canonical_event_type,
        semantic_action: editForm.semantic_action,
        extracted_entities: interpretation.canonical_event_type === "SETUP_EVENT"
          ? (setupEditEntities[interpretation.id] ?? [])
            .filter((entity) => entity.name.trim())
            .map((entity) => ({
              ...firstEntity(interpretation),
              name: entity.name,
              type: entity.type,
              project_role: entity.type,
              role_detail: entity.roleDetail || null,
              phone: entity.phone || null,
              account_number: entity.accountNumber || null,
              daily_rate: entity.type === "DAILY_WORKER" ? entity.dailyRate || null : null,
            }))
          : editForm.entity ? [{ ...firstEntity(interpretation), name: editForm.entity, type: editForm.entityType || "DAILY_WORKER" }] : [],
        extracted_amount: editForm.extracted_amount || null,
        extracted_quantity: editForm.extracted_quantity || null,
        payment_method: (editForm.payment_method || null) as PaymentType | null,
        due_date: editForm.due_date || null,
        description: editForm.description || null,
        structured_interpretation: structuredInterpretation,
      });
      setPendingInterpretations((items) => items.map((item) => item.id === updated.id ? updated : item));
      setEditingId(null);
    });
  }

  async function confirmInterpretation(interpretation: PendingInterpretation) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      await api.confirmPendingInterpretation(interpretation.id);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function updateWorkerProfile(workerId: number, payload: Partial<Pick<Worker, "name" | "type" | "role_detail" | "phone" | "account_number" | "daily_rate" | "notes">>) {
    if (!activeProjectId) return;
    await runAction("در حال ذخیره پروفایل", async () => {
      await api.updateWorker(workerId, payload);
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
    });
  }

  async function selectAmbiguousEntity(interpretation: PendingInterpretation, worker: Worker) {
    await runAction("در حال به‌روزرسانی فرد", async () => {
      const updated = await api.updatePendingInterpretation(interpretation.id, {
        suggested_entity_id: worker.id,
        extracted_entities: [{ ...firstEntity(interpretation), name: worker.name, type: worker.type }],
      });
      setPendingInterpretations((items) => items.map((item) => item.id === updated.id ? updated : item));
    });
  }

  async function resolveUnknownEntity(interpretation: PendingInterpretation) {
    const form = unknownEntityForms[interpretation.id];
    if (!form) return;
    const selectedWorker = workers.find((worker) => String(worker.id) === form.workerId);
    const name = selectedWorker?.name ?? form.name.trim();
    const type = selectedWorker?.type ?? form.type;
    if (!name) return;
    await runAction("در حال به‌روزرسانی فرد", async () => {
      const updated = await api.updatePendingInterpretation(interpretation.id, {
        suggested_entity_id: selectedWorker?.id ?? null,
        extracted_entities: [{ ...firstEntity(interpretation), name, type: type || "VENDOR", create_new: selectedWorker ? null : true }],
      });
      setPendingInterpretations((items) => items.map((item) => item.id === updated.id ? updated : item));
    });
  }

  async function discardInterpretation(interpretation: PendingInterpretation) {
    if (!activeProjectId) return;
    await runAction("در حال حذف برداشت", async () => {
      await api.discardPendingInterpretation(interpretation.id);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      await loadProjectData(activeProjectId);
    });
  }

  function renderPage() {
    if (route.name === "project") {
      return (
        <ProjectDetailPage
          project={projectDetail}
          summary={operatingSummary}
          workLogs={workLogs}
          payments={payments}
          invoices={invoices}
          history={history}
          rawEntries={rawEntries}
          text={naturalText}
          examples={exampleInputs}
          isLoading={loadingAction === "در حال پردازش ورودی"}
          onBack={() => navigate("/dashboard")}
          onTextChange={setNaturalText}
          onSubmit={submitNaturalInput}
          onVoicePlaceholder={() => setError("ضبط صدا در مسیر فعلی به صورت جای‌نگهدار فعال است.")}
          onAttachPlaceholder={() => setError("افزودن فایل در مسیر فعلی به صورت جای‌نگهدار فعال است.")}
          successMessage={successMessage}
        />
      );
    }
    if (route.name === "people" || route.name === "person") {
      return <PeoplePage workers={workers} workerStates={workerStates} payments={payments} workLogs={workLogs} invoices={invoices} summary={operatingSummary} selectedPersonId={route.name === "person" ? route.personId : null} onOpenPerson={(personId) => navigate(`/people/${personId}`)} onBackToPeople={() => navigate("/people")} onUpdateWorker={updateWorkerProfile} />;
    }
    if (route.name === "reports") return <ReportsPage projects={projects} project={projectDetail} summary={operatingSummary} workers={workers} workerStates={workerStates} payments={payments} invoices={invoices} />;
    return (
      <DashboardPage
        projects={projects}
        projectFinancials={projectFinancials}
        projectName={projectName}
        isLoading={isLoading}
        onProjectNameChange={setProjectName}
        onCreateProject={createProject}
        onOpenProject={openProject}
      />
    );
  }

  return (
    <main className="app-shell" dir="rtl">
      <aside className="sidebar">
        <div className="brand-block">
          <strong>Yara</strong>
        </div>
        <nav className="main-nav" aria-label="Primary navigation">
          {navItems.map((item) => (
            <button className={item.active ? "active" : ""} key={item.label} type="button" onClick={() => navigate(item.path)}>
              <NavIcon name={item.icon} />
              {item.label}
            </button>
          ))}
        </nav>
        <button className={openDebtCount > 0 ? "header-bell has-alerts" : "header-bell"} type="button" aria-label="هشدارها">
          <Bell aria-hidden="true" size={17} />
          <span>{openDebtCount.toLocaleString("fa-IR")}</span>
        </button>
      </aside>

      <section className="workspace">
        {error && <div className="error-banner">{error}</div>}
        {loadingAction && <div className="loading-banner">{loadingAction}...</div>}
        {renderPage()}
      </section>

      {pendingInterpretations.length > 0 && (
        <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="interpretation-title">
          <section className="confirmation-modal">
            <div className="modal-header">
              <div>
                <span className="eyebrow">تایید</span>
                <h2 id="interpretation-title">مورد پیشنهادی را قبل از ثبت بررسی کنید</h2>
                <p>هیچ چیزی بدون تایید شما در دفتر پروژه ثبت نمی‌شود.</p>
              </div>
            </div>

            <div className="interpretation-stack">
              {pendingInterpretations.map((interpretation) => {
                const isEditing = editingId === interpretation.id;
                const candidates = ambiguousEntityCandidates(interpretation, workers);
                if (candidates.length <= 1 && isUnresolvedVendorAutoCreate(interpretation)) {
                  return (
                    <article className="interpretation-card" key={interpretation.id}>
                      <section className="approval-section vendor-create-notice">
                        <h3>فروشنده: {entityName(interpretation)}</h3>
                        <p className="muted">فروشنده «{entityName(interpretation)}» در پروژه وجود ندارد.</p>
                        <p className="muted">در صورت تایید، فروشنده جدید ایجاد خواهد شد.</p>
                      </section>
                      <section className="approval-section">
                        <dl className="approval-fields">
                          {understoodRows(interpretation, workers).filter((row) => row.label !== "فروشنده").map((row) => <div key={`${row.label}-${row.value}`}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
                        </dl>
                      </section>
                      {interpretation.structured_interpretation && <StructuredDetails interpretation={interpretation} />}
                      {unsafeFinancialReason(interpretation) && <p className="warning-text">{unsafeFinancialReason(interpretation)}</p>}
                      <div className="modal-actions">
                        <button className="primary-action" type="button" onClick={() => confirmInterpretation(interpretation)} disabled={isLoading || Boolean(unsafeFinancialReason(interpretation))}>تایید</button>
                        <button type="button" onClick={() => startEdit(interpretation)} disabled={isLoading}>اصلاح</button>
                        <button className="danger-action" type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>لغو</button>
                      </div>
                    </article>
                  );
                }
                if (candidates.length <= 1 && (isUnknownEntity(interpretation) || needsFinancialEntityResolution(interpretation))) {
                  const form = unknownEntityForms[interpretation.id] ?? { workerId: "", name: entityName(interpretation) === "نامشخص" ? "" : entityName(interpretation), type: preferredEntityType(interpretation) };
                  const canContinue = Boolean(form.workerId || form.name.trim());
                  return (
                    <article className="interpretation-card" key={interpretation.id}>
                      <h3>{unresolvedEntityTitle(interpretation)}</h3>
                      <p className="muted">{unresolvedEntityHelp(interpretation)}</p>
                      <div className="edit-grid">
                        <label>انتخاب از افراد پروژه<select value={form.workerId} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, workerId: event.target.value } })}><option value="">انتخاب کنید...</option>{workers.map((worker) => <option key={worker.id} value={worker.id}>{worker.name} - {roleLabelFromType(worker.type)}</option>)}</select></label>
                        <label>نام<input value={form.name} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, name: event.target.value } })} /></label>
                        <label>نقش<select value={form.type} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, type: event.target.value } })}><option value="CLIENT">کارفرما</option><option value="VENDOR">فروشنده</option><option value="DAILY_WORKER">کارگر ساده</option><option value="SKILLED_WORKER">استادکار</option><option value="OTHER">سایر</option></select></label>
                      </div>
                      <div className="modal-actions">
                        <button className="primary-action" type="button" onClick={() => resolveUnknownEntity(interpretation)} disabled={isLoading || !canContinue}>ادامه</button>
                        <button type="button" onClick={() => startEdit(interpretation)} disabled={isLoading}>ویرایش</button>
                        <button className="danger-action" type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>حذف</button>
                      </div>
                    </article>
                  );
                }

                if (candidates.length > 1) {
                  const selectedCandidate = candidates.find((worker) => worker.id === ambiguitySelections[interpretation.id]);
                  return (
                    <article className="interpretation-card" key={interpretation.id}>
                      <h3>{preferredEntityType(interpretation) === "VENDOR" ? "کدام فروشنده مدنظر است؟" : `«${entityName(interpretation)}» کدام فرد است؟`}</h3>
                      <div className="entity-choice-list">
                        {candidates.map((worker) => (
                          <label key={worker.id} className="entity-choice">
                            <input type="radio" name={`entity-${interpretation.id}`} checked={ambiguitySelections[interpretation.id] === worker.id} onChange={() => setAmbiguitySelections({ ...ambiguitySelections, [interpretation.id]: worker.id })} />
                            <strong>{worker.name}</strong>
                            <span>{roleLabelFromType(worker.type)}</span>
                          </label>
                        ))}
                      </div>
                      <div className="modal-actions">
                        <button className="primary-action" type="button" onClick={() => selectedCandidate && selectAmbiguousEntity(interpretation, selectedCandidate)} disabled={isLoading || !selectedCandidate}>ادامه</button>
                        <button className="danger-action" type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>حذف</button>
                      </div>
                    </article>
                  );
                }

                return (
                  <article className="interpretation-card" key={interpretation.id}>
                    <section className="approval-section">
                      <span className="eyebrow">{approvalCategory(interpretation)}</span>
                      <dl className="approval-fields">
                        {understoodRows(interpretation, workers).map((row) => <div key={`${row.label}-${row.value}`}><dt>{row.label}</dt><dd>{row.value}</dd></div>)}
                      </dl>
                    </section>
                    <section className="approval-section">
                      <span className="eyebrow">نتیجه ثبت</span>
                      <div className="approval-outcome">{outcomeSummary(interpretation, workers).map((line) => <p key={line}>{line}</p>)}</div>
                    </section>
                    {interpretation.structured_interpretation && <StructuredDetails interpretation={interpretation} />}

                    {isEditing && (
                      interpretation.canonical_event_type === "SETUP_EVENT" ? (
                        <div className="setup-edit-list">
                          {(setupEditEntities[interpretation.id] ?? []).map((entity, index) => (
                            <div className="setup-edit-row" key={`${interpretation.id}-${index}`}>
                              <label>نام<input value={entity.name} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) })} /></label>
                              <label>نقش<select value={entity.type} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).map((item, itemIndex) => itemIndex === index ? { ...item, type: event.target.value } : item) })}><option value="CLIENT">کارفرما</option><option value="DAILY_WORKER">کارگر ساده</option><option value="SKILLED_WORKER">استادکار</option><option value="VENDOR">فروشنده</option><option value="OTHER">سایر</option></select></label>
                              {(entity.type === "SKILLED_WORKER" || entity.type === "OTHER") && <label>تخصص / توضیح نقش<input value={entity.roleDetail ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).map((item, itemIndex) => itemIndex === index ? { ...item, roleDetail: event.target.value } : item) })} /></label>}
                              <label>شماره موبایل<input value={entity.phone ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).map((item, itemIndex) => itemIndex === index ? { ...item, phone: event.target.value } : item) })} /></label>
                              <label>شماره حساب<input value={entity.accountNumber ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).map((item, itemIndex) => itemIndex === index ? { ...item, accountNumber: event.target.value } : item) })} /></label>
                              {entity.type === "DAILY_WORKER" && <label>دستمزد روزانه<input value={entity.dailyRate ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: (setupEditEntities[interpretation.id] ?? []).map((item, itemIndex) => itemIndex === index ? { ...item, dailyRate: event.target.value } : item) })} /></label>}
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="edit-grid">
                          <label>فرد<select value={editForm.entity ?? ""} onChange={(event) => {
                            const worker = workers.find((item) => item.name === event.target.value);
                            setEditForm({ ...editForm, entity: event.target.value, entityType: worker?.type ?? editForm.entityType });
                          }}><option value="">انتخاب کنید...</option>{workers.map((worker) => <option key={worker.id} value={worker.name}>{worker.name} - {roleLabelFromType(worker.type)}</option>)}</select></label>
                          <label>عملیات<select value={editForm.semantic_action ?? ""} onChange={(event) => setEditForm({ ...editForm, semantic_action: event.target.value })}><option value="PAYMENT">دریافتی/پرداخت</option><option value="PURCHASE_PAID">خرید پرداخت‌شده</option><option value="DEBT_CREATED">خرید نسیه / بدهی</option><option value="CHECK_PAYMENT">پرداخت چک</option><option value="INCREMENT">ثبت کارکرد</option></select></label>
                          <label>مبلغ<input value={editForm.extracted_amount ?? ""} onChange={(event) => setEditForm({ ...editForm, extracted_amount: event.target.value })} /></label>
                          <label>مقدار<input value={editForm.extracted_quantity ?? ""} onChange={(event) => setEditForm({ ...editForm, extracted_quantity: event.target.value })} /></label>
                          <label>واحد<select value={editForm.unit ?? ""} onChange={(event) => setEditForm({ ...editForm, unit: event.target.value })}><option value="day">روز</option><option value="meter">متر</option><option value="item">عدد</option><option value="project">پروژه</option><option value="custom">سفارشی</option></select></label>
                          <label>روش پرداخت<select value={editForm.payment_method ?? ""} onChange={(event) => setEditForm({ ...editForm, payment_method: event.target.value })}><option value="">انتخاب نشده</option><option value="CASH">نقدی</option><option value="BANK_TRANSFER">کارت/انتقال بانکی</option><option value="CHECK">چک</option><option value="OTHER">سایر</option></select></label>
                          <label>تاریخ سررسید<input value={editForm.due_date ?? ""} onChange={(event) => setEditForm({ ...editForm, due_date: event.target.value })} /></label>
                          <label className="wide-field">توضیح<textarea value={editForm.description ?? ""} onChange={(event) => setEditForm({ ...editForm, description: event.target.value })} /></label>
                        </div>
                      )
                    )}

                    {unsafeFinancialReason(interpretation) && <p className="warning-text">{unsafeFinancialReason(interpretation)}</p>}
                    <div className="modal-actions">
                      {isEditing ? <button className="primary-action" type="button" onClick={() => saveEdit(interpretation)} disabled={isLoading}>ذخیره ویرایش</button> : <button className="primary-action" type="button" onClick={() => confirmInterpretation(interpretation)} disabled={isLoading || Boolean(unsafeFinancialReason(interpretation))}>تایید</button>}
                      {isEditing ? <button type="button" onClick={() => setEditingId(null)} disabled={isLoading}>لغو ویرایش</button> : <button type="button" onClick={() => startEdit(interpretation)} disabled={isLoading}>ویرایش</button>}
                      <button className="danger-action" type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>حذف</button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

export default App;
