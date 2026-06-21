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
    const parsed = JSON.parse(err.message) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
    if (typeof parsed.detail === "object" && parsed.detail !== null) {
      const detail = parsed.detail as Record<string, unknown>;
      if (detail.status === "NEEDS_SELECTION") {
        const candidates = Array.isArray(detail.candidates) ? detail.candidates : [];
        if (candidates.length) return "برای ادامه، فرد مورد نظر را از فهرست انتخاب کنید.";
        return "برای ادامه، فرد جدید را تایید کنید یا اطلاعات را اصلاح کنید.";
      }
      return "درخواست کامل نبود. لطفا اطلاعات را بررسی کنید و دوباره تلاش کنید.";
    }
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

function candidateMatches(interpretation: PendingInterpretation, workers: Worker[]): Worker[] {
  const rawCandidates = firstEntity(interpretation).candidate_matches;
  if (!Array.isArray(rawCandidates)) return [];
  const ids = rawCandidates
    .map((candidate) => typeof candidate === "object" && candidate !== null && "person_id" in candidate ? Number((candidate as Record<string, unknown>).person_id) : null)
    .filter((id): id is number => Number.isFinite(id));
  return ids.map((id) => workers.find((worker) => worker.id === id)).filter((worker): worker is Worker => Boolean(worker));
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

function allowsVendorAutoCreate(_interpretation: PendingInterpretation): boolean {
  return false;
}

function needsFinancialEntityResolution(interpretation: PendingInterpretation): boolean {
  return interpretation.canonical_event_type === "FINANCIAL_EVENT" && !interpretation.suggested_entity_id && !hasExplicitCreateNew(interpretation) && !allowsVendorAutoCreate(interpretation);
}

function needsProfileEntityResolution(interpretation: PendingInterpretation): boolean {
  return interpretation.canonical_event_type === "SETUP_EVENT" && isEntityProfileUpdate(interpretation) && !hasExplicitCreateNew(interpretation);
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
  if (type === "DAILY_WORKER") return "کارگر";
  if (type === "OTHER") return "سایر";
  return "فرد";
}

function workerDisplayRole(worker: Worker): string {
  if ((worker.type === "SKILLED_WORKER" || worker.type === "OTHER") && worker.role_detail?.trim()) {
    return worker.role_detail.trim();
  }
  return roleLabelFromType(worker.type);
}

function workerOptionLabel(worker: Worker): string {
  return `${worker.name} - ${workerDisplayRole(worker)}`;
}

type SetupEntity = {
  name: string;
  type: string;
  roleDetail: string | null;
  phone: string | null;
  accountNumber: string | null;
  dailyRate: string | null;
  notes: string | null;
  roleUpdate: string | null;
};

type FlowType = "ROLE_FLOW" | "PROFILE_FLOW" | "FINANCIAL_FLOW";
type UnknownEntityForm = { workerId: string; name: string; type: string; roleDetail: string };
type EntityOverride = { name: string; type: string; roleDetail?: string | null };

function roleOptions(): Array<{ value: string; label: string }> {
  return [
    { value: "CLIENT", label: "کارفرما" },
    { value: "DAILY_WORKER", label: "کارگر" },
    { value: "VENDOR", label: "فروشنده" },
    { value: "SKILLED_WORKER", label: "استادکار" },
    { value: "OTHER", label: "سایر" },
  ];
}

function textValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number") return String(value);
  return null;
}

function setupEntities(interpretation: PendingInterpretation): SetupEntity[] {
  return (interpretation.extracted_entities ?? [])
    .map((entity) => {
      const updates = typeof entity.field_updates === "object" && entity.field_updates !== null ? entity.field_updates as Record<string, unknown> : {};
      return {
        name: typeof entity.name === "string" ? entity.name : "",
        type: entityTypeFromRecord(entity),
        roleDetail: textValue(updates.role_detail ?? entity.role_detail),
        phone: textValue(updates.phone ?? entity.phone),
        accountNumber: textValue(updates.account_number ?? entity.account_number),
        dailyRate: textValue(updates.daily_rate ?? entity.daily_rate),
        notes: textValue(updates.notes ?? entity.notes),
        roleUpdate: textValue(updates.project_role ?? updates.type),
      };
    })
    .filter((entity) => entity.name.trim());
}

function newEntityForm(interpretation: PendingInterpretation): UnknownEntityForm {
  const entity = setupEntities(interpretation)[0];
  return {
    workerId: "",
    name: entityName(interpretation) === "نامشخص" ? "" : entityName(interpretation),
    type: entity?.type ?? preferredEntityType(interpretation),
    roleDetail: entity?.roleDetail ?? "",
  };
}

function setupRoleLabel(type: string): string {
  return roleLabelFromType(type);
}

function shouldShowRoleDetail(type: string): boolean {
  return type === "SKILLED_WORKER" || type === "OTHER";
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

function isEntityProfileUpdate(interpretation: PendingInterpretation): boolean {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  return interpretation.semantic_action === "ENTITY_UPDATE" || si?.action === "UPDATE_ENTITY";
}

function isRoleAssignment(interpretation: PendingInterpretation): boolean {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  return interpretation.semantic_action === "SET_ROLE" || si?.intent === "SET_ROLE" || si?.action === "SET_ROLE";
}

function flowType(interpretation: PendingInterpretation): FlowType {
  if (isRoleAssignment(interpretation)) return "ROLE_FLOW";
  if (isEntityProfileUpdate(interpretation)) return "PROFILE_FLOW";
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") return "FINANCIAL_FLOW";
  return "PROFILE_FLOW";
}

function unresolvedEntityTitle(interpretation: PendingInterpretation): string {
  const name = entityName(interpretation);
  if (needsProfileEntityResolution(interpretation)) return `${name} در پروژه پیدا نشد.`;
  const role = setupRoleLabel(preferredEntityType(interpretation));
  if (name === "نامشخص" || name === "طرف حساب نامشخص") return "طرف حساب در پروژه پیدا نشد.";
  return `${role} «${name}» در پروژه پیدا نشد.`;
}

function unresolvedEntityHelp(interpretation: PendingInterpretation): string {
  if (needsProfileEntityResolution(interpretation)) return "فرد مورد نظر را انتخاب کنید یا فرد جدید بسازید.";
  const role = setupRoleLabel(preferredEntityType(interpretation));
  return `یک ${role} موجود را انتخاب کنید یا ${role} جدید ایجاد کنید.`;
}

function isUnresolvedVendorAutoCreate(interpretation: PendingInterpretation): boolean {
  return allowsVendorAutoCreate(interpretation);
}

function StructuredDetails(_props: { interpretation: PendingInterpretation }) {
  return null;
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
  if (interpretation.canonical_event_type === "SETUP_EVENT") {
    if (isEntityProfileUpdate(interpretation)) return "به‌روزرسانی اطلاعات فرد";
    if (isRoleAssignment(interpretation)) return "تعیین نقش فرد";
    return "ثبت فرد پروژه";
  }
  return "یادداشت پروژه";
}

function approvalCategory(interpretation: PendingInterpretation): string {
  if (interpretation.canonical_event_type === "SETUP_EVENT" && isEntityProfileUpdate(interpretation)) return "به‌روزرسانی اطلاعات فرد";
  if (interpretation.canonical_event_type === "SETUP_EVENT" && isRoleAssignment(interpretation)) return "تعیین نقش فرد";
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
    if (isEntityProfileUpdate(interpretation)) {
      return [
        { label: "فرد", value: entity },
        { label: "نقش", value: role },
        ...(setupEntity?.phone ? [{ label: "شماره تماس جدید", value: setupEntity.phone }] : []),
        ...(setupEntity?.accountNumber ? [{ label: "شماره حساب جدید", value: setupEntity.accountNumber }] : []),
        ...(setupEntity?.dailyRate ? [{ label: "دستمزد روزانه جدید", value: formatMoney(setupEntity.dailyRate) ?? setupEntity.dailyRate }] : []),
        ...(setupEntity?.notes ? [{ label: "یادداشت جدید", value: setupEntity.notes }] : []),
        ...(setupEntity?.roleUpdate ? [{ label: "نقش جدید", value: setupRoleLabel(setupEntity.roleUpdate) }] : []),
        ...(setupEntity?.roleDetail ? [{ label: "توضیح نقش جدید", value: setupEntity.roleDetail }] : []),
      ];
    }
    if (isRoleAssignment(interpretation)) {
      return [
        { label: "نام", value: entity },
        { label: "نقش", value: role },
      ];
    }
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
    if (isEntityProfileUpdate(interpretation)) {
      const setupEntity = entities[0];
      if (setupEntity?.phone) return [`شماره تماس ${entity} به ${setupEntity.phone} به‌روزرسانی می‌شود.`];
      if (setupEntity?.accountNumber) return [`شماره حساب ${entity} به ${setupEntity.accountNumber} به‌روزرسانی می‌شود.`];
      if (setupEntity?.dailyRate) return [`دستمزد روزانه ${entity} به ${formatMoney(setupEntity.dailyRate) ?? setupEntity.dailyRate} به‌روزرسانی می‌شود.`];
      if (setupEntity?.notes) return [`یادداشت ${entity} به‌روزرسانی می‌شود.`];
      if (setupEntity?.roleUpdate) return [`نقش ${entity} به ${setupRoleLabel(setupEntity.roleUpdate)} به‌روزرسانی می‌شود.`];
      if (setupEntity?.roleDetail) return [`توضیح نقش ${entity} به‌روزرسانی می‌شود.`];
      return [`اطلاعات ${entity} به‌روزرسانی می‌شود.`];
    }
    if (isRoleAssignment(interpretation)) {
      const setupEntity = entities[0];
      const role = setupRoleLabel(setupEntity?.type ?? "OTHER");
      return [`نقش ${entity} به ${role} تعیین می‌شود.`];
    }
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
  return candidateMatches(interpretation, workers);
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
  const [candidateSelections, setCandidateSelections] = useState<Record<number, string>>({});
  const [unknownEntityForms, setUnknownEntityForms] = useState<Record<number, UnknownEntityForm>>({});
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
      entityType: typeof entity.type === "string" ? entity.type : typeof entity.role_guess === "string" ? entity.role_guess : "OTHER",
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
      const updated = await updatePendingFromEditForm(interpretation);
      setPendingInterpretations((items) => items.map((item) => item.id === updated.id ? updated : item));
      setEditingId(null);
    });
  }

  function editValue(interpretation: PendingInterpretation, key: string, fallback: string | null | undefined): string {
    return editingId === interpretation.id || editForm.canonical_event_type ? editForm[key] ?? fallback ?? "" : fallback ?? "";
  }

  async function updatePendingFromEditForm(interpretation: PendingInterpretation): Promise<PendingInterpretation> {
    const currentWork = (interpretation.structured_interpretation?.work ?? {}) as Record<string, unknown>;
    const canonicalEventType = editValue(interpretation, "canonical_event_type", interpretation.canonical_event_type);
    const semanticAction = editValue(interpretation, "semantic_action", interpretation.semantic_action);
    const entityNameValue = editValue(interpretation, "entity", entityName(interpretation) === "نامشخص" ? "" : entityName(interpretation));
    const entityTypeValue = editValue(interpretation, "entityType", preferredEntityType(interpretation));
    const extractedAmountValue = editValue(interpretation, "extracted_amount", interpretation.extracted_amount);
    const extractedQuantityValue = editValue(interpretation, "extracted_quantity", interpretation.extracted_quantity);
    const unitValue = editValue(interpretation, "unit", workUnitFromInterpretation(interpretation));
    const paymentMethodValue = editValue(interpretation, "payment_method", interpretation.payment_method);
    const dueDateValue = editValue(interpretation, "due_date", interpretation.due_date);
    const descriptionValue = editValue(interpretation, "description", interpretation.description);
    const structuredInterpretation = interpretation.structured_interpretation
      ? {
        ...interpretation.structured_interpretation,
        work: {
          ...currentWork,
          quantity: extractedQuantityValue || currentWork.quantity || null,
          unit: unitValue || currentWork.unit || null,
          description: descriptionValue || currentWork.description || null,
        },
      }
      : null;
    return api.updatePendingInterpretation(interpretation.id, {
      canonical_event_type: canonicalEventType,
      semantic_action: semanticAction,
      extracted_entities: interpretation.canonical_event_type === "SETUP_EVENT"
        ? (setupEditEntities[interpretation.id] ?? setupEntities(interpretation))
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
        : entityNameValue ? [{ ...firstEntity(interpretation), name: entityNameValue, type: entityTypeValue || "OTHER", project_role: entityTypeValue || "OTHER" }] : [],
      extracted_amount: extractedAmountValue || null,
      extracted_quantity: extractedQuantityValue || null,
      payment_method: (paymentMethodValue || null) as PaymentType | null,
      due_date: dueDateValue || null,
      description: descriptionValue || null,
      structured_interpretation: structuredInterpretation,
    });
  }

  async function confirmEditedInterpretation(interpretation: PendingInterpretation, payload: { selected_person_id?: number | null; create_new?: boolean; name?: string | null; role?: string | null; role_detail?: string | null } = {}) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      await updatePendingFromEditForm(interpretation);
      await api.confirmPendingInterpretation(interpretation.id, payload);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmInterpretation(interpretation: PendingInterpretation, payload: { selected_person_id?: number | null; create_new?: boolean; name?: string | null; role?: string | null; role_detail?: string | null } = {}) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      await api.confirmPendingInterpretation(interpretation.id, payload);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmRoleInterpretation(
    interpretation: PendingInterpretation,
    payload: { selected_person_id?: number | null; create_new?: boolean; name?: string | null; role?: string | null; role_detail?: string | null } = {},
    entityOverride?: EntityOverride,
  ) {
    if (!activeProjectId) return;
    const roleEntities = entityOverride
      ? [{ name: entityOverride.name, type: entityOverride.type, roleDetail: entityOverride.roleDetail ?? null, phone: null, accountNumber: null, dailyRate: null }]
      : setupEditEntities[interpretation.id] ?? setupEntities(interpretation);
    const extractedEntities = roleEntities
      .filter((entity) => entity.name.trim())
      .map((entity) => ({
        name: entity.name,
        type: entity.type,
        project_role: entity.type,
        role_detail: entity.roleDetail || null,
      }));
    await runAction("در حال تایید", async () => {
      await api.updatePendingInterpretation(interpretation.id, {
        semantic_action: "SET_ROLE",
        extracted_entities: extractedEntities,
      });
      await api.confirmPendingInterpretation(interpretation.id, payload);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmCandidateInterpretation(
    interpretation: PendingInterpretation,
    payload: { selected_person_id?: number | null; create_new?: boolean; name?: string | null; role?: string | null; role_detail?: string | null },
    entityOverride?: EntityOverride,
  ) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      if (entityOverride) {
        await api.updatePendingInterpretation(interpretation.id, {
          extracted_entities: [{
            ...firstEntity(interpretation),
            name: entityOverride.name,
            type: entityOverride.type,
            project_role: entityOverride.type,
            role_detail: entityOverride.roleDetail || null,
          }],
        });
      }
      await api.confirmPendingInterpretation(interpretation.id, payload);
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
                const flow_type = flowType(interpretation);
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
                if (candidates.length === 0 && (isUnknownEntity(interpretation) || needsFinancialEntityResolution(interpretation) || needsProfileEntityResolution(interpretation) || interpretation.canonical_event_type === "SETUP_EVENT")) {
                  const form = unknownEntityForms[interpretation.id] ?? newEntityForm(interpretation);
                  const canContinue = Boolean(form.name.trim() && form.type);
                  return (
                    <article className="interpretation-card" key={interpretation.id}>
                      <h3>{unresolvedEntityTitle(interpretation)}</h3>
                      <p className="muted">{interpretation.canonical_event_type === "SETUP_EVENT" ? "این فرد به عنوان شخص جدید در پروژه ثبت می‌شود." : unresolvedEntityHelp(interpretation)}</p>
                      <div className="edit-grid">
                        <label>نام<input value={form.name} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, name: event.target.value } })} /></label>
                        <label>نقش<select value={form.type} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, type: event.target.value } })}>{roleOptions().map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
                        {shouldShowRoleDetail(form.type) && <label>تخصص / توضیح نقش<input value={form.roleDetail} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...form, roleDetail: event.target.value } })} /></label>}
                      </div>
                      <div className="modal-actions">
                        <button className="primary-action" type="button" onClick={() => {
                          const entityOverride = { name: form.name.trim(), type: form.type, roleDetail: form.roleDetail.trim() || null };
                          const createPayload = { create_new: true, name: entityOverride.name, role: entityOverride.type, role_detail: entityOverride.roleDetail };
                          if (flow_type === "ROLE_FLOW") {
                            confirmRoleInterpretation(interpretation, createPayload, entityOverride);
                          } else {
                            confirmCandidateInterpretation(interpretation, createPayload, entityOverride);
                          }
                        }} disabled={isLoading || !canContinue}>تأیید</button>
                        <button className="danger-action" type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>حذف</button>
                      </div>
                    </article>
                  );
                }

                if (candidates.length > 0) {
                  const selectionValue = candidateSelections[interpretation.id] ?? String(candidates[0].id);
                  const isCreatingNewCandidate = selectionValue === "create-new";
                  const selectedCandidate = isCreatingNewCandidate ? undefined : candidates.find((worker) => String(worker.id) === selectionValue) ?? candidates[0];
                  const roleEntities = setupEditEntities[interpretation.id] ?? setupEntities(interpretation);
                  const editableRoleEntities = roleEntities.length ? roleEntities : setupEntities(interpretation);
                  const createForm = unknownEntityForms[interpretation.id] ?? newEntityForm(interpretation);
                  const displayedName = isCreatingNewCandidate ? createForm.name : selectedCandidate?.name ?? "";
                  const displayedRole = isCreatingNewCandidate ? createForm.type : selectedCandidate?.type ?? preferredEntityType(interpretation);
                  const displayedRoleDetail = isCreatingNewCandidate ? createForm.roleDetail : selectedCandidate?.role_detail ?? "";
                  const canConfirmCandidate = Boolean(
                    isCreatingNewCandidate
                      ? createForm.name.trim() && createForm.type
                      : selectedCandidate
                  );
                  return (
                    <article className="interpretation-card" key={interpretation.id}>
                      <h3>{flow_type === "ROLE_FLOW" ? "تعیین نقش فرد" : preferredEntityType(interpretation) === "VENDOR" ? "کدام فروشنده مدنظر است؟" : `«${entityName(interpretation)}» کدام فرد است؟`}</h3>
                      {flow_type === "ROLE_FLOW" && <p className="muted">نقش این شخص در پروژه را مشخص کنید</p>}
                      <div className="edit-grid">
	                        <label>انتخاب فرد<select value={selectionValue} onChange={(event) => setCandidateSelections({ ...candidateSelections, [interpretation.id]: event.target.value })}>{candidates.map((worker) => <option key={worker.id} value={worker.id}>{workerOptionLabel(worker)}</option>)}<option value="create-new">ایجاد فرد جدید با نام «{entityName(interpretation)}»</option></select></label>
	                        <label>نام<input value={displayedName} readOnly={!isCreatingNewCandidate} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...createForm, name: event.target.value } })} /></label>
	                        {(isCreatingNewCandidate || flow_type === "ROLE_FLOW") ? (
	                          <>
	                            <label>نقش<select value={flow_type === "ROLE_FLOW" && !isCreatingNewCandidate ? editableRoleEntities[0]?.type ?? displayedRole : displayedRole} disabled={!isCreatingNewCandidate && flow_type !== "ROLE_FLOW"} onChange={(event) => {
	                              if (flow_type === "ROLE_FLOW" && !isCreatingNewCandidate) {
	                                setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableRoleEntities.map((item, itemIndex) => itemIndex === 0 ? { ...item, type: event.target.value } : item) });
	                              } else {
	                                setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...createForm, type: event.target.value } });
	                              }
	                            }}>{roleOptions().map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
	                            {shouldShowRoleDetail(displayedRole) && <label>تخصص / توضیح نقش<input value={displayedRoleDetail} readOnly={!isCreatingNewCandidate} onChange={(event) => setUnknownEntityForms({ ...unknownEntityForms, [interpretation.id]: { ...createForm, roleDetail: event.target.value } })} /></label>}
	                          </>
	                        ) : (
	                          <label>نقش فعلی<input value={selectedCandidate ? workerDisplayRole(selectedCandidate) : roleLabelFromType(displayedRole)} readOnly /></label>
	                        )}
	                      </div>
                      <div className="modal-actions">
                        <button className="primary-action" type="button" onClick={() => {
                          if (isCreatingNewCandidate) {
                            const entityOverride = { name: createForm.name.trim(), type: createForm.type, roleDetail: createForm.roleDetail.trim() || null };
                            const createPayload = { create_new: true, name: entityOverride.name, role: entityOverride.type, role_detail: entityOverride.roleDetail };
                            if (flow_type === "ROLE_FLOW") {
                              confirmRoleInterpretation(interpretation, createPayload, entityOverride);
                            } else {
                              confirmCandidateInterpretation(interpretation, createPayload, entityOverride);
                            }
                            return;
                          }
                          if (selectedCandidate) {
                            if (flow_type === "ROLE_FLOW") confirmRoleInterpretation(interpretation, { selected_person_id: selectedCandidate.id });
                            else confirmInterpretation(interpretation, { selected_person_id: selectedCandidate.id });
                          }
                        }} disabled={isLoading || !canConfirmCandidate}>تأیید</button>
                        {flow_type !== "ROLE_FLOW" && <button className="danger-action" type="button" onClick={() => discardInterpretation(interpretation)} disabled={isLoading}>حذف</button>}
                      </div>
                    </article>
                  );
                }

                if (flow_type === "ROLE_FLOW") {
                  const roleEntities = setupEditEntities[interpretation.id] ?? setupEntities(interpretation);
                  const editableEntities = roleEntities.length ? roleEntities : setupEntities(interpretation);
                  return (
                    <article className="interpretation-card" key={interpretation.id}>
                      <section className="approval-section">
                        <h3>تعیین نقش فرد</h3>
                        <p className="muted">نقش این شخص در پروژه را مشخص کنید</p>
                        <div className="edit-grid">
	                          {editableEntities.slice(0, 1).map((entity, index) => (
	                            <div className="setup-edit-row" key={`role-${interpretation.id}-${index}`}>
	                              <label>نام<input value={entity.name} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableEntities.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) })} /></label>
	                              <label>نقش<select value={entity.type} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableEntities.map((item, itemIndex) => itemIndex === index ? { ...item, type: event.target.value } : item) })}>{roleOptions().map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
	                              {shouldShowRoleDetail(entity.type) && <label>تخصص / توضیح نقش<input value={entity.roleDetail ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableEntities.map((item, itemIndex) => itemIndex === index ? { ...item, roleDetail: event.target.value } : item) })} /></label>}
	                            </div>
	                          ))}
                        </div>
                      </section>
                      <div className="modal-actions">
	                        <button className="primary-action" type="button" onClick={() => {
	                          const entity = editableEntities[0];
	                          confirmRoleInterpretation(interpretation, { create_new: true, name: entity.name.trim(), role: entity.type, role_detail: entity.roleDetail || null });
	                        }} disabled={isLoading || editableEntities.length === 0 || !editableEntities[0].name.trim()}>تأیید</button>
                      </div>
                    </article>
	                  );
	                }

	                const showEditableConfirmation = isEditing || flow_type === "PROFILE_FLOW" || flow_type === "FINANCIAL_FLOW";
	                const editableSetupEntities = setupEditEntities[interpretation.id] ?? setupEntities(interpretation);
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

	                    {showEditableConfirmation && (
	                      interpretation.canonical_event_type === "SETUP_EVENT" ? (
	                        <div className="setup-edit-list">
	                          {editableSetupEntities.map((entity, index) => (
	                            <div className="setup-edit-row" key={`${interpretation.id}-${index}`}>
	                              <label>نام<input value={entity.name} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableSetupEntities.map((item, itemIndex) => itemIndex === index ? { ...item, name: event.target.value } : item) })} /></label>
	                              {(entity.type === "SKILLED_WORKER" || entity.type === "OTHER") && <label>تخصص / توضیح نقش<input value={entity.roleDetail ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableSetupEntities.map((item, itemIndex) => itemIndex === index ? { ...item, roleDetail: event.target.value } : item) })} /></label>}
	                              <label>شماره موبایل<input value={entity.phone ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableSetupEntities.map((item, itemIndex) => itemIndex === index ? { ...item, phone: event.target.value } : item) })} /></label>
	                              <label>شماره حساب<input value={entity.accountNumber ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableSetupEntities.map((item, itemIndex) => itemIndex === index ? { ...item, accountNumber: event.target.value } : item) })} /></label>
	                              {entity.type === "DAILY_WORKER" && <label>دستمزد روزانه<input value={entity.dailyRate ?? ""} onChange={(event) => setSetupEditEntities({ ...setupEditEntities, [interpretation.id]: editableSetupEntities.map((item, itemIndex) => itemIndex === index ? { ...item, dailyRate: event.target.value } : item) })} /></label>}
	                            </div>
	                          ))}
	                        </div>
	                      ) : (
	                        <div className="edit-grid">
	                          <label>فرد<select value={editValue(interpretation, "entity", entityName(interpretation) === "نامشخص" ? "" : entityName(interpretation))} onChange={(event) => {
	                            const worker = workers.find((item) => item.name === event.target.value);
	                            setEditForm({ ...editForm, entity: event.target.value, entityType: worker?.type ?? editForm.entityType });
	                          }}><option value="">انتخاب کنید...</option>{workers.map((worker) => <option key={worker.id} value={worker.name}>{workerOptionLabel(worker)}</option>)}</select></label>
	                          <label>عملیات<select value={editValue(interpretation, "semantic_action", interpretation.semantic_action)} onChange={(event) => setEditForm({ ...editForm, semantic_action: event.target.value })}><option value="PAYMENT">دریافتی/پرداخت</option><option value="PURCHASE_PAID">خرید پرداخت‌شده</option><option value="DEBT_CREATED">خرید نسیه / بدهی</option><option value="CHECK_PAYMENT">پرداخت چک</option><option value="INCREMENT">ثبت کارکرد</option></select></label>
	                          <label>مبلغ<input value={editValue(interpretation, "extracted_amount", interpretation.extracted_amount)} onChange={(event) => setEditForm({ ...editForm, extracted_amount: event.target.value })} /></label>
	                          <label>مقدار<input value={editValue(interpretation, "extracted_quantity", interpretation.extracted_quantity)} onChange={(event) => setEditForm({ ...editForm, extracted_quantity: event.target.value })} /></label>
	                          <label>واحد<select value={editValue(interpretation, "unit", workUnitFromInterpretation(interpretation))} onChange={(event) => setEditForm({ ...editForm, unit: event.target.value })}><option value="day">روز</option><option value="meter">متر</option><option value="item">عدد</option><option value="project">پروژه</option><option value="custom">سفارشی</option></select></label>
	                          <label>روش پرداخت<select value={editValue(interpretation, "payment_method", interpretation.payment_method)} onChange={(event) => setEditForm({ ...editForm, payment_method: event.target.value })}><option value="">انتخاب نشده</option><option value="CASH">نقدی</option><option value="BANK_TRANSFER">کارت/انتقال بانکی</option><option value="CHECK">چک</option><option value="OTHER">سایر</option></select></label>
	                          <label>تاریخ سررسید<input value={editValue(interpretation, "due_date", interpretation.due_date)} onChange={(event) => setEditForm({ ...editForm, due_date: event.target.value })} /></label>
	                          <label className="wide-field">توضیح<textarea value={editValue(interpretation, "description", interpretation.description)} onChange={(event) => setEditForm({ ...editForm, description: event.target.value })} /></label>
	                        </div>
	                      )
	                    )}

                    {unsafeFinancialReason(interpretation) && <p className="warning-text">{unsafeFinancialReason(interpretation)}</p>}
                    <div className="modal-actions">
		                      <button className="primary-action" type="button" onClick={() => showEditableConfirmation ? confirmEditedInterpretation(interpretation, interpretation.canonical_event_type === "SETUP_EVENT" || hasExplicitCreateNew(interpretation) ? { create_new: true } : {}) : confirmInterpretation(interpretation, interpretation.canonical_event_type === "SETUP_EVENT" || hasExplicitCreateNew(interpretation) ? { create_new: true } : {})} disabled={isLoading || Boolean(unsafeFinancialReason(interpretation))}>تایید</button>
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
