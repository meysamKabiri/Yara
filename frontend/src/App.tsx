import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Activity, ArrowUpCircle, BarChart3, Bell, CheckCircle2, Clock, Home, LogOut, Plus, ReceiptText, Users } from "lucide-react";
import {
  api,
  FinancialDirection,
  HistoryEntry,
  Invoice,
  OperatingSummary,
  Payment,
  PaymentType,
  EntityResolutionResult,
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
import { JobDetailPage } from "./observability/pages/JobDetailPage";
import { JobsPage } from "./observability/pages/JobsPage";
import { toJobState, useNaturalInputJob } from "./observability/hooks/useNaturalInputJob";
import { DomainUIController } from "./ui/DomainUIController";
import { buildConfirmPayload, exactEntityIdByName, exactNeedsSelectionEntityId, normalizeNeedsSelection } from "./ui/confirmPayload";
import { SetupEntity } from "./types/domain";
import { AiProcessingStatus } from "./components/AiProcessingStatus";
import { AuthPage } from "./features/auth/AuthPage";
import { authApi, AUTH_TOKEN_KEY } from "./features/auth/authApi";
import { AuthUser } from "./features/auth/types";
import YaralogoUrl from './assets/images/Yara_logo.png'

const exampleInputs = [
  "کارفرمای پروژه میثم کبیری است",
  "مش رحیم امروز کار کرد",
  "نادری جوشکار امروز جوشکاری کرد",
  "۱۰۰ میلیون دادم به جوشکار",
  "میثم ۲۰۰ میلیون پول داد",
];

type Route =
  | { name: "dashboard" }
  | { name: "project"; projectId: number | null; tab?: string | null }
  | { name: "people" }
  | { name: "person"; personId: number }
  | { name: "reports" }
  | { name: "jobs" }
  | { name: "job"; jobId: string };

function parseRoute(pathname: string): Route {
  const projectMatch = pathname.match(/^\/projects\/(\d+)/);
  const personMatch = pathname.match(/^\/people\/(\d+)/);
  const jobMatch = pathname.match(/^\/jobs\/([^/]+)/);
  if (projectMatch) return { name: "project", projectId: Number(projectMatch[1]), tab: new URLSearchParams(window.location.search).get("tab") };
  if (personMatch) return { name: "person", personId: Number(personMatch[1]) };
  if (jobMatch) return { name: "job", jobId: decodeURIComponent(jobMatch[1]) };
  if (pathname === "/people") return { name: "people" };
  if (pathname === "/reports") return { name: "reports" };
  if (pathname === "/jobs") return { name: "jobs" };
  return { name: "dashboard" };
}

function NavIcon({ name }: { name: string }) {
  if (name === "home") return <Home aria-hidden="true" size={19} />;
  if (name === "users") return <Users aria-hidden="true" size={19} />;
  if (name === "activity") return <Activity aria-hidden="true" size={19} />;
  return <BarChart3 aria-hidden="true" size={19} />;
}

type ProjectCardFinancials = {
  received: number;
  paid: number;
  net: number;
  debt: number;
  labor: number;
  pending: number;
  deferred: number;
  clientName: string | null;
  lastActivity: string | null;
};

type NotificationItem = {
  id: string;
  projectId: number;
  tab: string;
  title: string;
  detail: string;
  amount?: number;
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

function firstEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  return interpretation.extracted_entities?.[0] ?? {};
}

type UnknownEntityForm = { workerId: string; name: string; type: string; roleDetail: string };
type EntityOverride = { name: string; type: string; roleDetail?: string | null };
type ConfirmPayload = { entity_id?: number | null; selected_person_id?: number | null; confirmed?: boolean; create_new?: boolean; name?: string | null; role?: string | null; role_detail?: string | null; amount?: string | null; direction?: FinancialDirection | null; payment_method?: PaymentType | null; description?: string | null; due_date?: string | null; field_updates?: Record<string, unknown> | null };

function textValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number") return String(value);
  return null;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
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

function workInfo(interpretation: PendingInterpretation): { quantity: string; periodLabel: string | null; description: string | null } {
  const structured = interpretation.structured_interpretation as Record<string, unknown> | null;
  const work = typeof structured?.work === "object" && structured.work !== null
    ? structured.work as Record<string, unknown>
    : {};
  return {
    quantity: textValue(interpretation.extracted_quantity ?? work.quantity) ?? "1",
    periodLabel: textValue(work.period_label),
    description: textValue(work.description) ?? interpretation.description ?? interpretation.matched_input_text ?? interpretation.raw_input_text ?? null,
  };
}

function workWorkerId(interpretation: PendingInterpretation, workers: Worker[]): number | null {
  if (interpretation.suggested_entity_id) return interpretation.suggested_entity_id;
  const entityName = textValue(firstEntity(interpretation).name);
  if (!entityName) return null;
  return exactEntityIdByName(entityName, workers);
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

async function confirmPendingWithSelectionRetry(
  interpretation: PendingInterpretation,
  entityId: number | null | undefined,
) {
  try {
    await api.confirmPendingInterpretation(interpretation.id, buildConfirmPayload(entityId ?? null));
  } catch (err) {
    const exactCandidateId = exactNeedsSelectionEntityId(normalizeNeedsSelection(err));
    if (!exactCandidateId) throw err;
    await api.confirmPendingInterpretation(interpretation.id, buildConfirmPayload(exactCandidateId));
  }
}



function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname));
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
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
  const [naturalInputJobId, setNaturalInputJobId] = useState<string | null>(null);
  const [setupEditEntities, setSetupEditEntities] = useState<Record<number, SetupEntity[]>>({});
  const [candidateSelections, setCandidateSelections] = useState<Record<number, string>>({});
  const [unknownEntityForms, setUnknownEntityForms] = useState<Record<number, UnknownEntityForm>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [pendingTabEditingId, setPendingTabEditingId] = useState<number | null>(null);
  const [reviewModalDismissed, setReviewModalDismissed] = useState(true);
  const [isNotificationOpen, setIsNotificationOpen] = useState(false);
  const notificationShellRef = useRef<HTMLDivElement>(null);
  const submittedTextRef = useRef("");
  const submittedIdempotencyKeyRef = useRef("");

  const isLoading = loadingAction !== null;
  const routeProjectId = route.name === "project" ? route.projectId : null;
  const activeProjectId = routeProjectId ?? selectedProjectId ?? null;
  const notificationItems = useMemo<NotificationItem[]>(() => {
    const items: NotificationItem[] = [];
    for (const project of projects) {
      const financials = projectFinancials[project.id];
      if (!financials) continue;
      if (financials.pending > 0) {
        items.push({
          id: `pending-${project.id}`,
          projectId: project.id,
          tab: "pending",
          title: `${financials.pending.toLocaleString("fa-IR")} مورد در انتظار تایید`,
          detail: project.name,
        });
      }
      if (financials.debt > 0) {
        items.push({
          id: `debt-${project.id}`,
          projectId: project.id,
          tab: "payables",
          title: "بدهی باز",
          detail: project.name,
          amount: financials.debt,
        });
      }
      if (financials.deferred > 0) {
        items.push({
          id: `deferred-${project.id}`,
          projectId: project.id,
          tab: "payables",
          title: "چک / پرداخت مدت‌دار",
          detail: project.name,
          amount: financials.deferred,
        });
      }
    }
    return items;
  }, [projectFinancials, projects]);
  const openDebtCount = notificationItems.length;
  const naturalInputJob = useNaturalInputJob(naturalInputJobId);
  const naturalInputJobState = useMemo(() => {
    return naturalInputJob.job ? toJobState(naturalInputJob.job.status, Boolean(naturalInputJobId)) : toJobState(null, Boolean(naturalInputJobId));
  }, [naturalInputJob.job, naturalInputJobId]);

  const navItems = useMemo(
    () => [
      { label: "خانه", path: "/dashboard", active: route.name === "dashboard" || route.name === "project", icon: "home" },
      { label: "افراد", path: "/people", active: route.name === "people" || route.name === "person", icon: "users" },
      { label: "گزارش‌ها", path: "/reports", active: route.name === "reports", icon: "reports" },
    ],
    [route.name],
  );

  const pageTitle = useMemo(() => {
    if (route.name === "dashboard") return "خانه";
    if (route.name === "project") return projectDetail?.name ?? "پروژه";
    if (route.name === "people" || route.name === "person") return "افراد";
    if (route.name === "reports") return "گزارش‌ها";
    if (route.name === "jobs") return "وظایف";
    if (route.name === "job") return "جزئیات";
    return "";
  }, [route.name, projectDetail?.name]);

  function handleRegister() {
    if (activeProjectId) {
      navigate(`/projects/${activeProjectId}`);
    } else {
      navigate("/dashboard");
    }
  }

  useEffect(() => {
    function handlePopState() {
      setRoute(parseRoute(window.location.pathname));
    }
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  useEffect(() => {
    async function checkAuth() {
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      if (!token) {
        setAuthChecked(true);
        return;
      }
      try {
        setAuthUser(await authApi.me());
      } catch {
        localStorage.removeItem(AUTH_TOKEN_KEY);
      } finally {
        setAuthChecked(true);
      }
    }
    checkAuth();
  }, []);

  useEffect(() => {
    if (!authChecked || !authUser) return;
    if (window.location.pathname === "/") navigate("/dashboard", true);
    loadProjects();
  }, [authChecked, authUser]);

  useEffect(() => {
    if (projects.length > 0) loadProjectFinancials(projects);
  }, [projects]);

  useEffect(() => {
    if (routeProjectId && routeProjectId !== selectedProjectId) setSelectedProjectId(routeProjectId);
  }, [routeProjectId, selectedProjectId]);

  useEffect(() => {
    if (!isNotificationOpen) return;
    function closeNotificationsOnOutsidePress(event: PointerEvent) {
      if (notificationShellRef.current?.contains(event.target as Node)) return;
      setIsNotificationOpen(false);
    }
    document.addEventListener("pointerdown", closeNotificationsOnOutsidePress);
    return () => document.removeEventListener("pointerdown", closeNotificationsOnOutsidePress);
  }, [isNotificationOpen]);

  useEffect(() => {
    if ((route.name === "people" || route.name === "reports") && !selectedProjectId && projects.length > 0) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, route.name, selectedProjectId]);

  useEffect(() => {
    if (activeProjectId) loadProjectData(activeProjectId);
  }, [activeProjectId]);

  useEffect(() => {
    if (naturalInputJob.state !== "DONE") return;
    const interpretations = naturalInputJob.interpretations;
    setPendingInterpretations(interpretations);
    const timer = setTimeout(() => setNaturalInputJobId(null), 600);
    return () => clearTimeout(timer);
  }, [naturalInputJob.state, naturalInputJob.job?.job_id, naturalInputJob.job?.updated_at]);

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

  function resetProjectState() {
    setProjects([]);
    setProjectName("");
    setSelectedProjectId(null);
    setProjectDetail(null);
    setRawEntries([]);
    setWorkers([]);
    setWorkerStates([]);
    setHistory([]);
    setInvoices([]);
    setPayments([]);
    setWorkLogs([]);
    setOperatingSummary(null);
    setProjectFinancials({});
    setNaturalText("");
    setPendingInterpretations([]);
    setNaturalInputJobId(null);
    setSetupEditEntities({});
    setCandidateSelections({});
    setUnknownEntityForms({});
    setPendingTabEditingId(null);
    setReviewModalDismissed(true);
    setIsNotificationOpen(false);
  }

  function handleAuthenticated(user: AuthUser) {
    setAuthUser(user);
    resetProjectState();
    setError(null);
    navigate("/dashboard", true);
  }

  function logout() {
    localStorage.removeItem(AUTH_TOKEN_KEY);
    setAuthUser(null);
    resetProjectState();
    navigate("/dashboard", true);
  }

  async function loadProjects() {
    await runAction("در حال بارگذاری پروژه‌ها", async () => setProjects(await api.listProjects()));
  }

  async function loadProjectFinancials(projectList: Project[]) {
    try {
      const entries = await Promise.all(
        projectList.map(async (project) => {
          const [projectPayments, summary, workerList, workLogList, pendingList] = await Promise.all([
            api.listPayments(project.id),
            api.getOperatingSummary(project.id),
            api.listWorkers(project.id),
            api.listWorkLogs(project.id),
            api.listPendingInterpretations(project.id),
          ]);
          const received = Number(summary.total_received_from_client ?? summary.total_received ?? 0);
          const paid = Number(summary.total_paid_out ?? 0);
          const debt = Number(summary.open_payables ?? 0);
          const deferred = Number(summary.deferred_amount || summary.check_amount || 0);
          const clientName = workerList.find((worker) => worker.type === "CLIENT")?.name ?? null;
          const latestActivity = [
            project.updated_at,
            ...projectPayments.map((payment) => payment.updated_at),
            ...workLogList.map((log) => log.updated_at),
            ...pendingList.map((pending) => pending.updated_at),
          ].sort((a, b) => Date.parse(b) - Date.parse(a))[0] ?? project.updated_at;
          const pending = pendingList.filter((item) => item.status === "PENDING" || item.status === "EDITED").length;
          return [project.id, {
            received,
            paid,
            debt,
            net: Number(summary.project_balance ?? received - paid - debt),
            labor: Number(summary.total_work_amount ?? 0),
            pending,
            deferred,
            clientName,
            lastActivity: latestActivity,
          }] as const;
        }),
      );
      setProjectFinancials(Object.fromEntries(entries));
    } catch (err) {
      setError(friendlyError(err));
    }
  }

  async function loadProjectData(projectId: number) {
    await runAction("در حال بارگذاری پروژه", async () => {
      const [detail, rawEntryList, workerList, states, historyList, invoiceList, paymentList, workLogList, summary, pendingList] = await Promise.all([
        api.getProject(projectId),
        api.listRawEntries(projectId),
        api.listWorkers(projectId),
        api.listWorkerStates(projectId),
        api.listHistory(projectId),
        api.listInvoices(projectId),
        api.listPayments(projectId),
        api.listWorkLogs(projectId),
        api.getOperatingSummary(projectId),
        api.listPendingInterpretations(projectId),
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
      setPendingInterpretations(pendingList);
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

  async function updateProject(projectId: number, payload: { name: string; description?: string | null }) {
    await runAction("در حال ویرایش پروژه", async () => {
      await api.updateProject(projectId, payload);
      const [projectList, detail] = await Promise.all([
        api.listProjects(),
        api.getProject(projectId),
      ]);
      setProjects(projectList);
      setProjectDetail(detail);
      setSuccessMessage("پروژه به‌روزرسانی شد");
      await loadProjectFinancials(projectList);
    });
  }

  async function refreshActiveProject() {
    if (!activeProjectId) return;
    await loadProjectData(activeProjectId);
  }

  async function correctPayment(projectId: number, paymentId: number, payload: Parameters<typeof api.correctPayment>[2]) {
    await runAction("در حال اصلاح پرداخت", async () => {
      await api.correctPayment(projectId, paymentId, payload);
      await refreshActiveProject();
    });
  }

  async function voidPayment(projectId: number, paymentId: number, reason?: string | null) {
    await runAction("در حال باطل کردن پرداخت", async () => {
      await api.voidPayment(projectId, paymentId, reason);
      await refreshActiveProject();
    });
  }

  async function correctWorkLog(projectId: number, workLogId: number, payload: Parameters<typeof api.correctWorkLog>[2]) {
    await runAction("در حال اصلاح کارکرد", async () => {
      await api.correctWorkLog(projectId, workLogId, payload);
      await refreshActiveProject();
    });
  }

  async function voidWorkLog(projectId: number, workLogId: number, reason?: string | null) {
    await runAction("در حال باطل کردن کارکرد", async () => {
      await api.voidWorkLog(projectId, workLogId, reason);
      await refreshActiveProject();
    });
  }

  async function correctPayable(projectId: number, payableId: number, payload: Parameters<typeof api.correctPayable>[2]) {
    await runAction("در حال اصلاح بدهی", async () => {
      await api.correctPayable(projectId, payableId, payload);
      await refreshActiveProject();
    });
  }

  async function voidPayable(projectId: number, payableId: number, reason?: string | null) {
    await runAction("در حال باطل کردن بدهی", async () => {
      await api.voidPayable(projectId, payableId, reason);
      await refreshActiveProject();
    });
  }

  async function correctNote(projectId: number, noteId: number, payload: { text: string; correction_note?: string | null }) {
    await runAction("در حال اصلاح یادداشت", async () => {
      await api.correctNote(projectId, noteId, payload);
      await refreshActiveProject();
    });
  }

  async function voidNote(projectId: number, noteId: number, reason?: string | null) {
    await runAction("در حال باطل کردن یادداشت", async () => {
      await api.voidNote(projectId, noteId, reason);
      await refreshActiveProject();
    });
  }

  async function submitNaturalInput(event: FormEvent) {
    event.preventDefault();
    if (isLoading) return;
    if (!activeProjectId) {
      setError("ابتدا پروژه را انتخاب کنید.");
      return;
    }
    if (!naturalText.trim()) return;
    const submittedText = naturalText.trim();
    const idempotencyKey = newIdempotencyKey();
    submittedTextRef.current = submittedText;
    submittedIdempotencyKeyRef.current = idempotencyKey;
    setNaturalText("");
    setPendingInterpretations([]);
    setReviewModalDismissed(false);
    setSuccessMessage(null);
    setError(null);
    await runAction("در حال ارسال ورودی", async () => {
      const job = await api.processNaturalInput(activeProjectId, submittedText, idempotencyKey);
      setNaturalInputJobId(job.job_id);
    });
  }

  function retryProcessing() {
    if (!activeProjectId || !submittedTextRef.current) return;
    setNaturalInputJobId(null);
    setError(null);
    setPendingInterpretations([]);
    setReviewModalDismissed(false);
    runAction("در حال ارسال ورودی", async () => {
      const idempotencyKey = submittedIdempotencyKeyRef.current || newIdempotencyKey();
      submittedIdempotencyKeyRef.current = idempotencyKey;
      const job = await api.processNaturalInput(activeProjectId, submittedTextRef.current, idempotencyKey);
      setNaturalInputJobId(job.job_id);
    });
  }

  function closeProcessing() {
    setNaturalInputJobId(null);
  }

  async function confirmSetupEntities(
    interpretation: PendingInterpretation,
    entities: SetupEntity[],
  ) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      const extractedEntities = entities
        .filter((e) => e.name.trim())
        .map((e) => ({
          name: e.name,
          type: e.type,
          project_role: e.type,
          role_detail: e.roleDetail || null,
          phone: e.phone || null,
          account_number: e.accountNumber || null,
          daily_rate: e.type === "DAILY_WORKER" ? e.dailyRate || null : null,
        }));
      await api.updatePendingInterpretation(interpretation.id, {
        semantic_action: "SET_ROLE",
        extracted_entities: extractedEntities,
      });
      const exactEntityId = extractedEntities.length === 1
        ? exactEntityIdByName(extractedEntities[0].name, workers)
        : null;
      await api.confirmPendingInterpretation(
        interpretation.id,
        exactEntityId ? { selected_person_id: exactEntityId } : { create_new: true },
      );
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      setNaturalInputJobId(null);
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmFinancialTransaction(
    interpretation: PendingInterpretation,
    data: { entity_id?: number | null; amount: string; direction: string; payment_method: string; description?: string | null; due_date?: string | null; create_new_entity?: boolean; entity_name?: string; project_role?: string },
  ) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      const editPayload = {
        amount: data.amount || null,
        direction: data.direction ? data.direction as FinancialDirection : null,
        payment_method: data.payment_method ? data.payment_method as PaymentType : null,
        description: data.description ?? null,
        due_date: data.due_date ?? null,
      };
      if (data.create_new_entity) {
        const resolution = await api.confirmPendingInterpretation(interpretation.id, {
          create_new: true,
          name: data.entity_name,
          role: data.project_role,
          ...editPayload,
        }) as EntityResolutionResult;
        await api.confirmPendingInterpretation(interpretation.id, {
          entity_id: resolution.entity_id,
          confirmed: true,
          ...editPayload,
        });
      } else {
        const confirmPayload: ConfirmPayload = {
          confirmed: true,
          ...editPayload,
        };
        if (typeof data.entity_id === "number") confirmPayload.entity_id = data.entity_id;
        await api.confirmPendingInterpretation(interpretation.id, confirmPayload);
      }
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      setNaturalInputJobId(null);
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmMixedInterpretation(
    interpretation: PendingInterpretation,
    setupEntities: SetupEntity[],
    financialData: { entity_id: number; amount: string; direction: string; payment_method: string },
  ) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      await api.updatePendingInterpretation(interpretation.id, {
        semantic_action: "SET_ROLE",
        extracted_entities: setupEntities
          .filter((e) => e.name.trim())
          .map((e) => ({
            name: e.name,
            type: e.type,
            project_role: e.type,
            role_detail: e.roleDetail || null,
            phone: e.phone || null,
            account_number: e.accountNumber || null,
          })),
        suggested_entity_id: financialData.entity_id,
        extracted_amount: financialData.amount || null,
        financial_direction: financialData.direction as FinancialDirection,
        payment_method: financialData.payment_method as PaymentType,
      });
      await api.confirmPendingInterpretation(interpretation.id, {
        entity_id: financialData.entity_id,
        confirmed: true,
      });
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      setNaturalInputJobId(null);
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmEntityUpdateAction(
    interpretation: PendingInterpretation,
    data: { entityId?: number | null; name: string; phone: string | null; accountNumber: string | null; dailyRate: string | null; role: string; roleDetail: string | null; create_new_entity?: boolean; entity_name?: string; project_role?: string; field_updates?: Record<string, unknown>; _skipApiConfirm?: boolean },
  ) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      // If the modal already confirmed the interpretation (NEEDS_SELECTION path),
      // just do cleanup without re-confirming the API
      if (data._skipApiConfirm) {
        setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
        setNaturalInputJobId(null);
        await loadProjectData(activeProjectId);
        await loadProjectFinancials(projects);
        setSuccessMessage("ثبت شد");
        window.setTimeout(() => setSuccessMessage(null), 2600);
        return;
      }

      const updates: Record<string, string | null> = {};
      if (data.phone) updates.phone = data.phone;
      if (data.accountNumber) updates.account_number = data.accountNumber;
      if (data.dailyRate) updates.daily_rate = data.dailyRate;
      if (data.role) updates.project_role = data.role;
      if (data.roleDetail) updates.role_detail = data.roleDetail;

      if (data.create_new_entity) {
        await api.confirmPendingInterpretation(interpretation.id, {
          create_new: true,
          name: data.entity_name || data.name,
          role: data.project_role || data.role,
          field_updates: data.field_updates,
        });
      } else {
        await api.updatePendingInterpretation(interpretation.id, {
          extracted_entities: [
            {
              ...firstEntity(interpretation),
              name: data.name,
              field_updates: updates,
            },
          ],
        });
        await confirmPendingWithSelectionRetry(
          interpretation,
          data.entityId ?? interpretation.suggested_entity_id ?? null,
        );
      }
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      setNaturalInputJobId(null);
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  function openProject(projectId: number) {
    setSelectedProjectId(projectId);
    navigate(`/projects/${projectId}`);
  }

  function openProjectTab(projectId: number, tab: string) {
    setSelectedProjectId(projectId);
    setIsNotificationOpen(false);
    navigate(`/projects/${projectId}?tab=${encodeURIComponent(tab)}`);
  }

  async function confirmFinancialInterpretation(interpretation: PendingInterpretation, payload: ConfirmPayload = {}) {
    const selectedId = payload.entity_id ?? payload.selected_person_id ?? interpretation.suggested_entity_id ?? null;
    if (selectedId && !payload.create_new) {
      await api.confirmPendingInterpretation(interpretation.id, { entity_id: selectedId, confirmed: true });
      return;
    }
    const resolutionPayload: ConfirmPayload = {
      create_new: payload.create_new,
      name: payload.name,
      role: payload.role,
      role_detail: payload.role_detail,
      selected_person_id: payload.selected_person_id ?? null,
    };
    if (payload.entity_id !== undefined) resolutionPayload.entity_id = payload.entity_id;
    const resolution = await api.confirmPendingInterpretation(interpretation.id, resolutionPayload);
    if (!isEntityResolutionResult(resolution)) return;
    await api.confirmPendingInterpretation(interpretation.id, { entity_id: resolution.entity_id, confirmed: true });
  }

  function isEntityResolutionResult(value: unknown): value is EntityResolutionResult {
    return Boolean(value && typeof value === "object" && (value as EntityResolutionResult).status === "ENTITY_RESOLVED");
  }

  async function confirmInterpretation(interpretation: PendingInterpretation, payload: ConfirmPayload = {}) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      if (interpretation.canonical_event_type === "FINANCIAL_EVENT") await confirmFinancialInterpretation(interpretation, payload);
      else await api.confirmPendingInterpretation(interpretation.id, payload);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      setNaturalInputJobId(null);
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmRoleInterpretation(
    interpretation: PendingInterpretation,
    payload: ConfirmPayload = {},
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
      if (interpretation.canonical_event_type === "FINANCIAL_EVENT") await confirmFinancialInterpretation(interpretation, payload);
      else await api.confirmPendingInterpretation(interpretation.id, payload);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      setNaturalInputJobId(null);
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmCandidateInterpretation(
    interpretation: PendingInterpretation,
    payload: ConfirmPayload,
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
      if (interpretation.canonical_event_type === "FINANCIAL_EVENT") await confirmFinancialInterpretation(interpretation, payload);
      else await api.confirmPendingInterpretation(interpretation.id, payload);
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      setNaturalInputJobId(null);
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
      setNaturalInputJobId(null);
      await loadProjectData(activeProjectId);
    });
  }

  async function discardPendingFromDetail(interpretation: PendingInterpretation) {
    if (!window.confirm("این مورد نادیده گرفته شود؟")) return;
    await discardInterpretation(interpretation);
    setSuccessMessage("نادیده گرفته شد");
    window.setTimeout(() => setSuccessMessage(null), 2600);
  }

  async function confirmPendingFromDetail(interpretation: PendingInterpretation) {
    const entity = firstEntity(interpretation);
    const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
      ? entity.field_updates as Record<string, unknown>
      : {};
    const entityName = textValue(entity.name) ?? "نامشخص";
    const role = entityTypeFromRecord(entity);
    const exactEntityId = interpretation.suggested_entity_id ?? exactEntityIdByName(entityName, workers);

    if (interpretation.canonical_event_type === "FINANCIAL_EVENT") {
      await confirmInterpretation(interpretation, exactEntityId
        ? { entity_id: exactEntityId }
        : {
          create_new: true,
          name: entityName,
          role,
        });
      return;
    }
    if (interpretation.canonical_event_type === "WORK_EVENT" || interpretation.semantic_action === "WORK_LOG") {
      const work = workInfo(interpretation);
      await confirmInterpretation(interpretation, {
        entity_id: workWorkerId(interpretation, workers),
        confirmed: true,
        field_updates: {
          quantity_days: work.quantity,
          period_label: work.periodLabel,
          description: work.description,
        },
      });
      return;
    }
    if (interpretation.semantic_action === "ENTITY_UPDATE" || interpretation.domain_route?.domain === "ENTITY_UPDATE") {
      await confirmEntityUpdateAction(interpretation, {
        entityId: exactEntityId,
        name: entityName,
        phone: textValue(updates.phone ?? entity.phone),
        accountNumber: textValue(updates.account_number ?? entity.account_number),
        dailyRate: textValue(updates.daily_rate ?? entity.daily_rate),
        role,
        roleDetail: textValue(updates.role_detail ?? entity.role_detail),
        create_new_entity: !exactEntityId,
        entity_name: entityName,
        project_role: role,
        field_updates: updates,
      });
      return;
    }
    if (interpretation.semantic_action === "SET_ROLE") {
      if (exactEntityId) {
        await confirmRoleInterpretation(interpretation, { selected_person_id: exactEntityId });
      } else {
        await confirmSetupEntities(interpretation, setupEntities(interpretation));
      }
      return;
    }
    await confirmInterpretation(interpretation, { confirmed: true });
  }

  function renderPage() {
    if (route.name === "project") {
      return (
        <ProjectDetailPage
          project={projectDetail}
          summary={operatingSummary}
          workers={workers}
          pendingInterpretations={pendingInterpretations}
          workLogs={workLogs}
          payments={payments}
          invoices={invoices}
          history={history}
          rawEntries={rawEntries}
          text={naturalText}
          examples={exampleInputs}
          isLoading={loadingAction === "در حال ارسال ورودی" || naturalInputJobId !== null}
          onBack={() => navigate("/dashboard")}
          onTextChange={setNaturalText}
          onSubmit={submitNaturalInput}
          onVoicePlaceholder={() => setError("ضبط صدا در مسیر فعلی به صورت جای‌نگهدار فعال است.")}
          onAttachPlaceholder={() => setError("افزودن فایل در مسیر فعلی به صورت جای‌نگهدار فعال است.")}
          successMessage={successMessage}
          requestedTab={route.tab ?? null}
          onConfirmPending={confirmPendingFromDetail}
          onEditPending={(interpretation) => setPendingTabEditingId(interpretation.id)}
          onDiscardPending={discardPendingFromDetail}
          onCorrectPayment={correctPayment}
          onVoidPayment={voidPayment}
          onCorrectWorkLog={correctWorkLog}
          onVoidWorkLog={voidWorkLog}
          onCorrectPayable={correctPayable}
          onVoidPayable={voidPayable}
          onCorrectNote={correctNote}
          onVoidNote={voidNote}
          onUpdateProject={updateProject}
        />
      );
    }
    if (route.name === "people" || route.name === "person") {
      return <PeoplePage projects={projects} selectedProjectId={activeProjectId} onProjectChange={(projectId) => { setSelectedProjectId(projectId); navigate("/people"); }} workers={workers} workerStates={workerStates} payments={payments} workLogs={workLogs} invoices={invoices} summary={operatingSummary} selectedPersonId={route.name === "person" ? route.personId : null} onOpenPerson={(personId) => navigate(`/people/${personId}`)} onBackToPeople={() => navigate("/people")} onUpdateWorker={updateWorkerProfile} />;
    }
    if (route.name === "reports") return <ReportsPage projects={projects} selectedProjectId={activeProjectId} onProjectChange={setSelectedProjectId} />;
    if (route.name === "jobs") return <JobsPage onOpenJob={(jobId) => navigate(`/jobs/${encodeURIComponent(jobId)}`)} />;
    if (route.name === "job") return <JobDetailPage jobId={route.jobId} onBack={() => navigate("/jobs")} />;
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

  if (!authChecked) {
    return (
      <main className="auth-shell" dir="rtl">
        <div className="loading-banner">در حال بررسی ورود...</div>
      </main>
    );
  }

  if (!authUser) {
    return <AuthPage onAuthenticated={handleAuthenticated} />;
  }

  return (
    <main className="app-shell" dir="rtl">
      <header className="app-header">
        <div className="app-header-inner">
          <div className="brand-block">
            {/* <strong>Yara</strong> */}
            <img src={YaralogoUrl} height={30} width={80} />
            <span className="mobile-page-title">{pageTitle}</span>
          </div>

          <nav className="main-nav" aria-label="Primary navigation">
            {navItems.map((item) => (
              <button className={item.active ? "active" : ""} key={item.label} type="button" onClick={() => navigate(item.path)}>
                <NavIcon name={item.icon} />
                {item.label}
              </button>
            ))}
          </nav>

          <div className="header-user-cluster">
            <span className="header-user-email" title={authUser.email}>{authUser.email}</span>
            <div className="notification-shell" ref={notificationShellRef}>
              <button className={openDebtCount > 0 ? "header-bell has-alerts" : "header-bell"} type="button" aria-label="هشدارها" onClick={() => setIsNotificationOpen((value) => !value)}>
                <Bell aria-hidden="true" size={17} />
                <span>{openDebtCount.toLocaleString("fa-IR")}</span>
              </button>
              {isNotificationOpen && (
                <div className="notification-dropdown">
                  <div className="notification-dropdown-head">
                    <strong>اعلان‌ها</strong>
                    <span>{notificationItems.length.toLocaleString("fa-IR")} مورد</span>
                  </div>
                  {notificationItems.length === 0 ? (
                    <p className="notification-empty"><CheckCircle2 size={16} />اعلان جدیدی وجود ندارد</p>
                  ) : (
                    <div className="notification-list">
                      {notificationItems.map((item) => (
                        <button key={item.id} type="button" onClick={() => openProjectTab(item.projectId, item.tab)}>
                          {item.tab === "pending" ? <Clock aria-hidden="true" size={16} /> : item.tab === "payables" ? <ReceiptText aria-hidden="true" size={16} /> : <ArrowUpCircle aria-hidden="true" size={16} />}
                          <span>
                            <strong>{item.title}</strong>
                            <small>{item.detail}{item.amount !== undefined ? ` — ${Number(item.amount).toLocaleString("fa-IR")} تومان` : ""}</small>
                          </span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
            <button className="text-button header-logout" type="button" onClick={logout} aria-label="خروج" title="خروج">
              <LogOut aria-hidden="true" size={17} />
            </button>
          </div>
        </div>
      </header>

      <section className="workspace">
        {error && <div className="error-banner">{error}</div>}
        {loadingAction && <div className="loading-banner">{loadingAction}...</div>}
        {renderPage()}
      </section>

      <nav className="mobile-bottom-nav" aria-label="Mobile navigation">
        <button className={(route.name === "dashboard" || route.name === "project") ? "active" : ""} type="button" onClick={() => navigate("/dashboard")}>
          <Home aria-hidden="true" size={20} />
          <span>خانه</span>
        </button>
        <button className={(route.name === "people" || route.name === "person") ? "active" : ""} type="button" onClick={() => navigate("/people")}>
          <Users aria-hidden="true" size={20} />
          <span>افراد</span>
        </button>
        <button type="button" onClick={handleRegister}>
          <Plus aria-hidden="true" size={20} />
          <span>ثبت</span>
        </button>
        <button className={route.name === "reports" ? "active" : ""} type="button" onClick={() => navigate("/reports")}>
          <BarChart3 aria-hidden="true" size={20} />
          <span>گزارش‌ها</span>
        </button>
      </nav>

      {naturalInputJobId !== null && (
        <AiProcessingStatus
          jobState={naturalInputJob.state}
          error={naturalInputJob.error}
          onRetry={retryProcessing}
          onClose={closeProcessing}
        />
      )}

      {(pendingTabEditingId || (!reviewModalDismissed && pendingInterpretations.length > 0)) && (
        <DomainUIController
          interpretations={pendingTabEditingId
            ? pendingInterpretations.filter((interpretation) => interpretation.id === pendingTabEditingId)
            : pendingInterpretations}
          jobState={naturalInputJobState}
          jobEvents={[]}
          jobConnectionState={naturalInputJobId ? "POLLING" : "IDLE"}
          jobError={naturalInputJob.error}
          workers={workers}
          activeProjectId={activeProjectId}
          projectName={projectDetail?.name ?? null}
          isLoading={isLoading}
          setupEditEntities={setupEditEntities}
          candidateSelections={candidateSelections}
          unknownEntityForms={unknownEntityForms}
          setSetupEditEntities={setSetupEditEntities}
          setCandidateSelections={setCandidateSelections}
          setUnknownEntityForms={setUnknownEntityForms}
          onConfirm={async (interpretation, payload) => {
            await confirmInterpretation(interpretation, payload);
            setPendingTabEditingId(null);
          }}
          onConfirmFinancial={confirmFinancialInterpretation}
          onConfirmRole={async (interpretation, payload, entityOverride) => {
            await confirmRoleInterpretation(interpretation, payload, entityOverride);
            setPendingTabEditingId(null);
          }}
          onConfirmCandidate={async (interpretation, payload, entityOverride) => {
            await confirmCandidateInterpretation(interpretation, payload, entityOverride);
            setPendingTabEditingId(null);
          }}
          onDiscard={async (interpretation) => {
            await discardInterpretation(interpretation);
            setPendingTabEditingId(null);
          }}
          onResolveUnknownEntity={resolveUnknownEntity}
          onClose={() => {
            setReviewModalDismissed(true);
            setPendingTabEditingId(null);
          }}
          onConfirmSetupEntities={async (interpretation, entities) => {
            await confirmSetupEntities(interpretation, entities);
            setPendingTabEditingId(null);
          }}
          onConfirmFinancialTransaction={async (interpretation, data) => {
            await confirmFinancialTransaction(interpretation, data);
            setPendingTabEditingId(null);
          }}
          onConfirmMixed={async (interpretation, setup, financial) => {
            await confirmMixedInterpretation(interpretation, setup, financial);
            setPendingTabEditingId(null);
          }}
          onConfirmEntityUpdate={async (interpretation, data) => {
            await confirmEntityUpdateAction(interpretation, data);
            setPendingTabEditingId(null);
          }}
        />
      )}
    </main>
  );
}

export default App;
