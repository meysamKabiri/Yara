import { FormEvent, useEffect, useMemo, useState } from "react";
import { BarChart3, Bell, Home, Users } from "lucide-react";
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
  TraceDetail,
  Worker,
  WorkerState,
  WorkLog,
  subscribeToTraceIds,
} from "./api";
import { TraceViewer } from "./components/TraceViewer";
import { DashboardPage } from "./pages/DashboardPage";
import { PeoplePage } from "./pages/PeoplePage";
import { ProjectDetailPage } from "./pages/ProjectDetailPage";
import { ReportsPage } from "./pages/ReportsPage";
import { DomainUIController } from "./ui/DomainUIController";
import { SetupEntity } from "./types/domain";

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

function firstEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  return interpretation.extracted_entities?.[0] ?? {};
}

type UnknownEntityForm = { workerId: string; name: string; type: string; roleDetail: string };
type EntityOverride = { name: string; type: string; roleDetail?: string | null };
type ConfirmPayload = { entity_id?: number | null; selected_person_id?: number | null; confirmed?: boolean; create_new?: boolean; name?: string | null; role?: string | null; role_detail?: string | null };

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
  const [setupEditEntities, setSetupEditEntities] = useState<Record<number, SetupEntity[]>>({});
  const [candidateSelections, setCandidateSelections] = useState<Record<number, string>>({});
  const [unknownEntityForms, setUnknownEntityForms] = useState<Record<number, UnknownEntityForm>>({});
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [latestTrace, setLatestTrace] = useState<TraceDetail | null>(null);

  const isLoading = loadingAction !== null;
  const routeProjectId = route.name === "project" ? route.projectId : null;
  const activeProjectId = routeProjectId ?? selectedProjectId ?? null;
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
    let isMounted = true;

    const pending = new Set<string>();
    const seen = new Set<string>();

    let timer: number | null = null;

    const processBatch = async () => {
      if (!isMounted) return;

      const batch = Array.from(pending);
      pending.clear();

      for (const traceId of batch) {
        if (seen.has(traceId)) continue;
        seen.add(traceId);

        try {
          const trace = await api.getTrace(traceId);

          if (!isMounted) return;

          setLatestTrace(trace);
        } catch (err) {
          if (!isMounted) return;

          setLatestTrace({
            trace_id: traceId,
            events: [],
          });
        }
      }
    };

    const unsubscribe = subscribeToTraceIds((traceId: string) => {
      pending.add(traceId);

      if (!timer) {
        timer = window.setTimeout(() => {
          processBatch();
          timer = null;
        }, 300); // slightly safer throttle
      }
    });

    return () => {
      isMounted = false;
      pending.clear();
      seen.clear();

      if (timer) clearTimeout(timer);

      unsubscribe?.();
    };
  }, []);

  useEffect(() => {
    if (projects.length > 0) loadProjectFinancials(projects);
  }, [projects]);

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
    if (!activeProjectId) {
      setError("ابتدا پروژه را انتخاب کنید.");
      return;
    }
    if (!naturalText.trim()) return;
    const submittedText = naturalText.trim();
    await runAction("در حال پردازش ورودی", async () => {
      setSuccessMessage(null);
      const result = await api.processNaturalInput(activeProjectId, submittedText);
      setPendingInterpretations(result.interpretations);
      setNaturalText("");
    });
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
      await api.confirmPendingInterpretation(interpretation.id, { create_new: true });
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmFinancialTransaction(
    interpretation: PendingInterpretation,
    data: { entity_id: number; amount: string; direction: string; payment_method: string },
  ) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      await api.updatePendingInterpretation(interpretation.id, {
        suggested_entity_id: data.entity_id,
        extracted_amount: data.amount || null,
        financial_direction: data.direction as FinancialDirection,
        payment_method: data.payment_method as PaymentType,
      });
      await api.confirmPendingInterpretation(interpretation.id, {
        entity_id: data.entity_id,
        confirmed: true,
      });
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
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
      await loadProjectData(activeProjectId);
      await loadProjectFinancials(projects);
      setSuccessMessage("ثبت شد");
      window.setTimeout(() => setSuccessMessage(null), 2600);
    });
  }

  async function confirmEntityUpdateAction(
    interpretation: PendingInterpretation,
    data: { name: string; phone: string | null; accountNumber: string | null; role: string; roleDetail: string | null },
  ) {
    if (!activeProjectId) return;
    await runAction("در حال تایید", async () => {
      const updates: Record<string, string | null> = {};
      if (data.phone) updates.phone = data.phone;
      if (data.accountNumber) updates.account_number = data.accountNumber;
      if (data.role) updates.project_role = data.role;
      if (data.roleDetail) updates.role_detail = data.roleDetail;

      await api.updatePendingInterpretation(interpretation.id, {
        extracted_entities: [
          {
            ...firstEntity(interpretation),
            name: data.name,
            field_updates: updates,
          },
        ],
      });
      await api.confirmPendingInterpretation(interpretation.id, {});
      setPendingInterpretations((items) => items.filter((item) => item.id !== interpretation.id));
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

  async function confirmFinancialInterpretation(interpretation: PendingInterpretation, payload: ConfirmPayload = {}) {
    const selectedId = payload.entity_id ?? payload.selected_person_id ?? interpretation.suggested_entity_id ?? null;
    if (selectedId && !payload.create_new) {
      await api.confirmPendingInterpretation(interpretation.id, { entity_id: selectedId, confirmed: true });
      return;
    }
    const resolution = await api.confirmPendingInterpretation(interpretation.id, {
      create_new: payload.create_new,
      name: payload.name,
      role: payload.role,
      role_detail: payload.role_detail,
      selected_person_id: payload.selected_person_id ?? null,
      entity_id: payload.entity_id ?? null,
    });
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
        {/* <TraceViewer trace={latestTrace} /> */}
      </section>

      <DomainUIController
        interpretations={pendingInterpretations}
        workers={workers}
        activeProjectId={activeProjectId}
        isLoading={isLoading}
        setupEditEntities={setupEditEntities}
        candidateSelections={candidateSelections}
        unknownEntityForms={unknownEntityForms}
        setSetupEditEntities={setSetupEditEntities}
        setCandidateSelections={setCandidateSelections}
        setUnknownEntityForms={setUnknownEntityForms}
        onConfirm={confirmInterpretation}
        onConfirmFinancial={confirmFinancialInterpretation}
        onConfirmRole={confirmRoleInterpretation}
        onConfirmCandidate={confirmCandidateInterpretation}
        onDiscard={discardInterpretation}
        onResolveUnknownEntity={resolveUnknownEntity}
        onConfirmSetupEntities={confirmSetupEntities}
        onConfirmFinancialTransaction={confirmFinancialTransaction}
        onConfirmMixed={confirmMixedInterpretation}
        onConfirmEntityUpdate={confirmEntityUpdateAction}
      />
    </main>
  );
}

export default App;
