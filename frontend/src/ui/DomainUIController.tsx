import { useRef, useState } from "react";
import type { JobEvent, JobState, PendingInterpretation, Worker } from "../api";
import { ROLE_OPTIONS } from "../constants";
import type { SetupEntity } from "../types/domain";
import { SetupModal } from "./setup/SetupModal";
import { FinancialModal } from "./financial/FinancialModal";
import { EntityUpdateModal } from "./entity/EntityUpdateModal";
import { SplitFlowModal } from "./split/SplitFlowModal";
import { exactEntityIdByName, normalizeEntityName } from "./confirmPayload";

type UnknownEntityForm = { workerId: string; name: string; type: string; roleDetail: string };
type EntityOverride = { name: string; type: string; roleDetail?: string | null };
type ConfirmPayload = {
  entity_id?: number | null;
  selected_person_id?: number | null;
  confirmed?: boolean;
  create_new?: boolean;
  name?: string | null;
  role?: string | null;
  role_detail?: string | null;
  field_updates?: Record<string, unknown> | null;
};

type ModalKind = "MIXED" | "FINANCIAL" | "PROFILE" | "WORK" | "ROLE_OR_SETUP" | "NOTE" | "UNKNOWN";

interface DomainUIControllerProps {
  interpretations: PendingInterpretation[];
  jobState?: JobState;
  jobEvents?: JobEvent[];
  jobConnectionState?: string;
  jobError?: string | null;
  workers: Worker[];
  activeProjectId: number | null;
  projectName?: string | null;
  isLoading: boolean;

  setupEditEntities: Record<number, SetupEntity[]>;
  candidateSelections: Record<number, string>;
  unknownEntityForms: Record<number, UnknownEntityForm>;

  setSetupEditEntities: (entities: Record<number, SetupEntity[]>) => void;
  setCandidateSelections: (selections: Record<number, string>) => void;
  setUnknownEntityForms: (forms: Record<number, UnknownEntityForm>) => void;

  onConfirm: (interpretation: PendingInterpretation, payload?: ConfirmPayload) => Promise<void>;
  onConfirmFinancial: (interpretation: PendingInterpretation, payload?: ConfirmPayload) => Promise<void>;
  onConfirmRole: (interpretation: PendingInterpretation, payload?: ConfirmPayload, entityOverride?: EntityOverride) => Promise<void>;
  onConfirmCandidate: (interpretation: PendingInterpretation, payload: ConfirmPayload, entityOverride?: EntityOverride) => Promise<void>;
  onDiscard: (interpretation: PendingInterpretation) => Promise<void>;
  onResolveUnknownEntity: (interpretation: PendingInterpretation) => Promise<void>;

  onConfirmSetupEntities: (interpretation: PendingInterpretation, entities: SetupEntity[]) => Promise<void>;
  onConfirmFinancialTransaction: (
    interpretation: PendingInterpretation,
    data: { entity_id?: number | null; amount: string; direction: string; payment_method: string; description?: string | null; due_date?: string | null; create_new_entity?: boolean; entity_name?: string; project_role?: string },
  ) => Promise<void>;
  onConfirmMixed: (
    interpretation: PendingInterpretation,
    setupEntities: SetupEntity[],
    financialData: { entity_id: number; amount: string; direction: string; payment_method: string },
  ) => Promise<void>;
  onClose?: () => void;
  onConfirmEntityUpdate: (
    interpretation: PendingInterpretation,
    data: { entityId?: number | null; name: string; phone: string | null; accountNumber: string | null; dailyRate: string | null; role: string; roleDetail: string | null; create_new_entity?: boolean; entity_name?: string; project_role?: string; field_updates?: Record<string, unknown> },
  ) => Promise<void>;
}

function firstEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  return interpretation.extracted_entities?.[0] ?? {};
}

function entityName(interpretation: PendingInterpretation): string {
  const entity = firstEntity(interpretation);
  return typeof entity.name === "string" && entity.name.trim() ? entity.name.trim() : "نامشخص";
}

function exactWorkerIdForProfile(interpretation: PendingInterpretation, workers: Worker[]): number | null {
  const suggestedId = interpretation.suggested_entity_id;
  if (suggestedId) return suggestedId;
  const name = entityName(interpretation);
  if (!name || isUnknownEntity(interpretation)) return null;
  return exactEntityIdByName(name, workers);
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
    .map((candidate) =>
      typeof candidate === "object" && candidate !== null && "person_id" in candidate
        ? Number((candidate as Record<string, unknown>).person_id)
        : null,
    )
    .filter((id): id is number => Number.isFinite(id));
  return ids.map((id) => workers.find((worker) => worker.id === id)).filter((worker): worker is Worker => Boolean(worker));
}

function shouldPreferQualifiedRoleCreateNew(name: string, candidates: Worker[]): boolean {
  const normalized = normalizeEntityName(name);
  if (!normalized.includes("تاسیساتی")) return false;
  return !candidates.some((worker) => normalizeEntityName(worker.name) === normalized);
}

function allowsVendorAutoCreate(_interpretation: PendingInterpretation): boolean {
  return false;
}

function structuredEntities(interpretation: PendingInterpretation): Array<Record<string, unknown>> {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  return Array.isArray(si?.entities)
    ? si.entities.filter((entity): entity is Record<string, unknown> => typeof entity === "object" && entity !== null)
    : [];
}

function entityHasProfileUpdateFields(entity: Record<string, unknown>): boolean {
  const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
    ? entity.field_updates as Record<string, unknown>
    : {};
  return Boolean(
    textValue(updates.phone ?? entity.phone)
    || textValue(updates.account_number ?? updates.accountNumber ?? entity.account_number ?? entity.accountNumber)
    || textValue(updates.card_number ?? entity.card_number)
    || textValue(updates.daily_rate ?? updates.dailyRate ?? entity.daily_rate ?? entity.dailyRate)
    || textValue(updates.notes ?? entity.notes)
  );
}

function hasProfileUpdateFields(interpretation: PendingInterpretation): boolean {
  return [...(interpretation.extracted_entities ?? []), ...structuredEntities(interpretation)]
    .some(entityHasProfileUpdateFields);
}

function isRoleAssignment(interpretation: PendingInterpretation): boolean {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  return interpretation.semantic_action === "SET_ROLE" || si?.intent === "SET_ROLE" || si?.action === "SET_ROLE";
}

function hasActualFinancialData(interpretation: PendingInterpretation): boolean {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  const financial = typeof si?.financial === "object" && si.financial !== null
    ? si.financial as Record<string, unknown>
    : {};
  const financialActions = new Set([
    "PAYMENT",
    "PAYMENT_IN",
    "PAYMENT_OUT",
    "PAYMENT_RECEIVED",
    "PURCHASE_PAID",
    "PURCHASE_UNPAID",
    "DEBT_CREATED",
    "CHECK_PAYMENT",
  ]);
  const direction = String(interpretation.financial_direction ?? financial.direction ?? "").toUpperCase();
  return Boolean(
    interpretation.extracted_amount
    || textValue(financial.amount)
    || (direction && direction !== "NONE")
    || (interpretation.canonical_event_type === "FINANCIAL_EVENT" && financialActions.has(interpretation.semantic_action)),
  );
}

function getModalKind(interpretation: PendingInterpretation): ModalKind {
  if (interpretation.domain_route?.domain === "MIXED") return "MIXED";
  if (interpretation.semantic_action === "WORK_LOG" || interpretation.canonical_event_type === "WORK_EVENT") return "WORK";
  if (interpretation.semantic_action === "NOTE") return "NOTE";
  if (hasActualFinancialData(interpretation)) return "FINANCIAL";
  if (hasProfileUpdateFields(interpretation)) return "PROFILE";
  if (
    interpretation.domain_route?.domain === "SETUP" ||
    interpretation.domain_route?.domain === "FINANCIAL" ||
    interpretation.domain_route?.domain === "ENTITY_UPDATE" ||
    isRoleAssignment(interpretation) ||
    interpretation.canonical_event_type === "SETUP_EVENT" ||
    interpretation.canonical_event_type === "FINANCIAL_EVENT"
  ) return "ROLE_OR_SETUP";
  return "UNKNOWN";
}

function needsFinancialEntityResolution(interpretation: PendingInterpretation): boolean {
  return interpretation.canonical_event_type === "FINANCIAL_EVENT" && !interpretation.suggested_entity_id && !hasExplicitCreateNew(interpretation) && !allowsVendorAutoCreate(interpretation);
}

function needsProfileEntityResolution(interpretation: PendingInterpretation): boolean {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  return interpretation.canonical_event_type === "SETUP_EVENT" && !hasExplicitCreateNew(interpretation) && (
    interpretation.semantic_action === "ENTITY_UPDATE"
    || si?.action === "UPDATE_ENTITY"
    || interpretation.domain_route?.domain === "ENTITY_UPDATE"
    || interpretation.domain_route?.ui_mode === "EntityUpdateModal"
  );
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

function setupEntities(interpretation: PendingInterpretation): SetupEntity[] {
  return (interpretation.extracted_entities ?? [])
    .map((entity) => {
      const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
        ? entity.field_updates as Record<string, unknown>
        : {};
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

function textValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number") return String(value);
  return null;
}

function moneyLabel(value: string | null): string | null {
  if (!value) return null;
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return value;
  return `${new Intl.NumberFormat("fa-IR").format(numeric)} تومان`;
}

function workInfo(interpretation: PendingInterpretation): { quantity: string; periodLabel: string; description: string } {
  const structured = interpretation.structured_interpretation as Record<string, unknown> | null;
  const work = typeof structured?.work === "object" && structured.work !== null
    ? structured.work as Record<string, unknown>
    : {};
  return {
    quantity: textValue(interpretation.extracted_quantity ?? work.quantity) ?? "1",
    periodLabel: textValue(work.period_label) ?? "",
    description: textValue(work.description) ?? interpretation.description ?? interpretation.matched_input_text ?? interpretation.raw_input_text,
  };
}

function workWorkerId(interpretation: PendingInterpretation, workers: Worker[]): number | null {
  if (interpretation.suggested_entity_id) return interpretation.suggested_entity_id;
  const name = entityName(interpretation);
  if (!name || isUnknownEntity(interpretation)) return null;
  return exactEntityIdByName(name, workers);
}

function WorkLogModal({
  interpretation,
  workers,
  isLoading,
  onConfirm,
  onDiscard,
  onLater,
}: {
  interpretation: PendingInterpretation;
  workers: Worker[];
  isLoading: boolean;
  onConfirm: (payload: ConfirmPayload) => void;
  onDiscard: () => void;
  onLater?: () => void;
}) {
  const initial = workInfo(interpretation);
  const initialWorkerId = workWorkerId(interpretation, workers);
  const [workerChoice, setWorkerChoice] = useState(initialWorkerId ? String(initialWorkerId) : "");
  const [newWorkerName, setNewWorkerName] = useState(entityName(interpretation) === "نامشخص" ? "" : entityName(interpretation));
  const [quantity, setQuantity] = useState(initial.quantity);
  const [periodLabel, setPeriodLabel] = useState(initial.periodLabel);
  const [description, setDescription] = useState(initial.description);
  const selectedWorker = workers.find((worker) => String(worker.id) === workerChoice);
  const isCreateNew = workerChoice === "create-new";
  const dailyRate = selectedWorker?.daily_rate ?? null;
  const amount = dailyRate && Number.isFinite(Number(quantity))
    ? String(Number(dailyRate) * Number(quantity))
    : null;
  const canConfirm = isCreateNew ? newWorkerName.trim().length > 0 : Boolean(selectedWorker);

  function submit() {
    const field_updates = {
      quantity_days: quantity.trim(),
      period_label: periodLabel.trim() || null,
      description: description.trim() || null,
    };
    if (isCreateNew) {
      onConfirm({
        confirmed: true,
        create_new: true,
        name: newWorkerName.trim(),
        role: "DAILY_WORKER",
        field_updates,
      });
      return;
    }
    onConfirm({
      entity_id: selectedWorker?.id ?? null,
      confirmed: true,
      field_updates,
    });
  }

  return (
    <article className="interpretation-card">
      <h3>ثبت کارکرد کارگر</h3>
      <p className="muted">{interpretation.matched_input_text || interpretation.raw_input_text}</p>
      <div className="edit-grid">
        <label>
          فرد / کارگر
          <select value={workerChoice} onChange={(event) => setWorkerChoice(event.target.value)}>
            <option value="">انتخاب کنید...</option>
            {workers.filter((worker) => worker.type === "DAILY_WORKER").map((worker) => (
              <option key={worker.id} value={worker.id}>
                {workerOptionLabel(worker)}
              </option>
            ))}
            <option value="create-new">ایجاد کارگر جدید</option>
          </select>
        </label>
        {isCreateNew && (
          <label>
            نام کارگر
            <input value={newWorkerName} onChange={(event) => setNewWorkerName(event.target.value)} />
          </label>
        )}
        <label>
          تعداد روز
          <input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} />
        </label>
        <label>
          نرخ روزانه
          <input value={dailyRate ? moneyLabel(dailyRate) ?? dailyRate : "نرخ روزانه ثبت نشده"} readOnly />
        </label>
        <label>
          مبلغ کارکرد
          <input value={amount ? moneyLabel(amount) ?? amount : "نرخ روزانه ثبت نشده"} readOnly />
        </label>
        <label>
          بازه / توضیح زمان
          <input value={periodLabel} onChange={(event) => setPeriodLabel(event.target.value)} />
        </label>
        <label className="wide-field">
          توضیحات
          <textarea value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
      </div>
      <div className="modal-actions">
        <button className="primary-action" type="button" onClick={submit} disabled={isLoading || !canConfirm || !quantity.trim()}>
          تایید
        </button>
        <button type="button" onClick={onLater ?? onDiscard} disabled={isLoading}>
          بعدا بررسی می‌کنم
        </button>
        <button className="danger-action" type="button" onClick={onDiscard} disabled={isLoading}>
          نادیده گرفتن
        </button>
      </div>
    </article>
  );
}



function profileFieldKind(interpretation: PendingInterpretation): "phone" | "account" | null {
  const entities = [...(interpretation.extracted_entities ?? []), ...structuredEntities(interpretation)];
  for (const entity of entities) {
    const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
      ? entity.field_updates as Record<string, unknown>
      : {};
    if (textValue(updates.phone ?? entity.phone)) return "phone";
    if (textValue(updates.account_number ?? updates.accountNumber ?? entity.account_number ?? entity.accountNumber)) return "account";
  }
  return null;
}

function interpretationLabel(interpretation: PendingInterpretation): string {
  if (interpretation.semantic_action === "WORK_LOG" || interpretation.canonical_event_type === "WORK_EVENT") return "ثبت کارکرد کارگر";
  const profileKind = profileFieldKind(interpretation);
  if (profileKind === "phone") return "ثبت شماره تماس";
  if (profileKind === "account") return "ثبت شماره حساب";
  if (interpretation.semantic_action === "PURCHASE_PAID") return "خرید پرداخت‌شده";
  if (interpretation.canonical_event_type === "FINANCIAL_EVENT") {
    if (interpretation.financial_direction === "INCOMING") return "دریافت از کارفرما / دریافتی";
    if (interpretation.financial_direction === "OUTGOING") return "پرداختی";
    return "رویداد مالی";
  }
  if (interpretation.canonical_event_type === "SETUP_EVENT" || isRoleAssignment(interpretation)) return "تعریف طرف حساب";
  return "مورد پیشنهادی";
}

function reviewText(interpretation: PendingInterpretation): string {
  return interpretation.matched_input_text || interpretation.description || interpretation.raw_input_text;
}

function roleForCreate(interpretation: PendingInterpretation): string {
  return preferredEntityType(interpretation) || "OTHER";
}

interface MultiInterpretationReviewProps {
  interpretations: PendingInterpretation[];
  isLoading: boolean;
  onEdit: (interpretation: PendingInterpretation) => void;
  onConfirm: (interpretation: PendingInterpretation) => void;
  onDiscard: (interpretation: PendingInterpretation) => void;
}

function needsReview(interpretation: PendingInterpretation): boolean {
  return (
    (interpretation.confidence !== null && interpretation.confidence < 0.5) ||
    (interpretation.suggested_entity_id === null && entityName(interpretation) === "نامشخص")
  );
}

function MultiInterpretationReview({
  interpretations,
  isLoading,
  onEdit,
  onConfirm,
  onDiscard,
}: MultiInterpretationReviewProps) {
  return (
    <section className="multi-review">
      <div className="multi-review-header">
        <span className="eyebrow">{interpretations.length} مورد شناسایی شد</span>
      </div>
      <div className="multi-review-list">
        {interpretations.map((interpretation) => {
          const counterparty = entityName(interpretation);
          const isUnknownCounterparty = counterparty === "نامشخص";
          const warning = needsReview(interpretation);
          return (
            <article className="multi-review-card" key={interpretation.id}>
              <div className="multi-review-card-main">
                <strong>
                  {interpretationLabel(interpretation)}
                  {warning && <span className="warning-dot" title="نیاز به بررسی">●</span>}
                </strong>
                <p className="review-text-preview">{reviewText(interpretation)}</p>
                <dl className="multi-review-meta">
                  {interpretation.extracted_amount && (
                    <>
                      <dt>مقدار</dt>
                      <dd className="amount-value">{moneyLabel(interpretation.extracted_amount)}</dd>
                    </>
                  )}
                  {!isUnknownCounterparty && (
                    <>
                      <dt>طرف حساب</dt>
                      <dd>{counterparty}</dd>
                    </>
                  )}
                </dl>
              </div>
              <div className="multi-review-actions">
                <button className={`primary-action${warning ? " primary-action--caution" : ""}`} type="button" onClick={() => onConfirm(interpretation)} disabled={isLoading}>
                  تایید
                </button>
                <button type="button" onClick={() => onEdit(interpretation)} disabled={isLoading}>
                  ویرایش
                </button>
                <button className="danger-action" type="button" onClick={() => onDiscard(interpretation)} disabled={isLoading}>
                  حذف
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
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

function shouldShowRoleDetail(type: string): boolean {
  return type === "SKILLED_WORKER" || type === "OTHER";
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

function unresolvedEntityTitle(interpretation: PendingInterpretation): string {
  const name = entityName(interpretation);
  if (needsProfileEntityResolution(interpretation)) return `${name} در پروژه پیدا نشد.`;
  const role = roleLabelFromType(preferredEntityType(interpretation));
  if (name === "نامشخص" || name === "طرف حساب نامشخص") return "طرف حساب در پروژه پیدا نشد.";
  return `${role} «${name}» در پروژه پیدا نشد.`;
}

function unresolvedEntityHelp(interpretation: PendingInterpretation): string {
  if (needsProfileEntityResolution(interpretation)) return "فرد مورد نظر را انتخاب کنید یا فرد جدید بسازید.";
  const role = roleLabelFromType(preferredEntityType(interpretation));
  return `یک ${role} موجود را انتخاب کنید یا ${role} جدید ایجاد کنید.`;
}

export function DomainUIController({
  interpretations,
  jobState,
  jobEvents,
  jobConnectionState,
  jobError,
  workers = [],
  activeProjectId,
  projectName,
  isLoading,
  setupEditEntities,
  candidateSelections,
  unknownEntityForms,
  setSetupEditEntities,
  setCandidateSelections,
  setUnknownEntityForms,
  onConfirm,
  onConfirmFinancial,
  onConfirmRole,
  onConfirmCandidate,
  onDiscard,
  onResolveUnknownEntity,
  onConfirmSetupEntities,
  onConfirmFinancialTransaction,
  onConfirmMixed,
  onClose,
  onConfirmEntityUpdate,
}: DomainUIControllerProps) {

  const safeInterpretations = interpretations ?? [];
  const safeWorkers = workers ?? [];
  const isJobActive = jobState && jobState !== "IDLE";
  const isJobDone = jobState === "DONE";
  const [editingInterpretationId, setEditingInterpretationId] = useState<number | null>(null);
  const editingInterpretation = editingInterpretationId
    ? safeInterpretations.find((interpretation) => interpretation.id === editingInterpretationId) ?? null
    : null;
  const shouldShowMultiReview = safeInterpretations.length > 1 && editingInterpretation === null;
  const visibleInterpretations = editingInterpretation ? [editingInterpretation] : safeInterpretations;

  const splitSetupData = useRef<{
    name: string;
    type: string;
    roleDetail: string | null;
    phone: string | null;
    accountNumber: string | null;
  } | null>(null);

  if (safeInterpretations.length === 0 && !isJobActive) return null;

  function confirmFromReview(interpretation: PendingInterpretation) {
    const kind = getModalKind(interpretation);
    if (kind === "FINANCIAL") {
      onConfirmFinancialTransaction(interpretation, {
        entity_id: interpretation.suggested_entity_id,
        amount: interpretation.extracted_amount ?? "",
        direction: interpretation.financial_direction ?? "",
        payment_method: interpretation.payment_method ?? "",
        create_new_entity: !interpretation.suggested_entity_id && !isUnknownEntity(interpretation),
        entity_name: entityName(interpretation),
        project_role: roleForCreate(interpretation),
      });
      return;
    }
    if (kind === "PROFILE") {
      const entity = firstEntity(interpretation);
      const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
        ? entity.field_updates as Record<string, unknown>
        : {};
      onConfirmEntityUpdate(interpretation, {
        entityId: exactWorkerIdForProfile(interpretation, safeWorkers),
        name: entityName(interpretation),
        phone: textValue(updates.phone ?? entity.phone),
        accountNumber: textValue(updates.account_number ?? entity.account_number),
        dailyRate: textValue(updates.daily_rate ?? entity.daily_rate),
        role: preferredEntityType(interpretation),
        roleDetail: textValue(updates.role_detail ?? entity.role_detail),
        field_updates: updates,
      });
      return;
    }
    if (kind === "WORK") {
      const entityId = workWorkerId(interpretation, safeWorkers);
      const work = workInfo(interpretation);
      onConfirm(interpretation, {
        entity_id: entityId,
        confirmed: true,
        field_updates: {
          quantity_days: work.quantity,
          period_label: work.periodLabel || null,
          description: work.description || null,
        },
      });
      return;
    }
    if (kind === "ROLE_OR_SETUP") {
      onConfirmSetupEntities(interpretation, setupEntities(interpretation));
      return;
    }
    onConfirm(interpretation, { confirmed: true });
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="interpretation-title">
      <section className="confirmation-modal">
        <div className="modal-header">
          <div>
            <span className="eyebrow">بررسی</span>
            {safeInterpretations.length > 1 ? (
              <>
                <h2 id="interpretation-title">بررسی موارد استخراج‌شده</h2>
                <p>موارد زیر از متن شما شناسایی شد. تایید، آن‌ها را در پروژه ثبت می‌کند؛ می‌توانید هر مورد را ویرایش کنید یا برای بررسی بعدی نگه دارید.</p>
              </>
            ) : safeInterpretations.length === 1 ? (
              <>
                <h2 id="interpretation-title">بررسی اطلاعات</h2>
                <p>اگر تایید کنید، همین اطلاعات در پروژه ثبت می‌شود. برای اصلاح، ویرایش کنید؛ برای نگه داشتن در صف، بعدا بررسی کنید.</p>
              </>
            ) : (
              <>
                <h2 id="interpretation-title">درخواست شما در صف پردازش است</h2>
                <p>پردازش غیرهمزمان انجام می‌شود؛ تایید بعد از پایان پردازش فعال می‌شود</p>
              </>
            )}
          </div>
          {onClose && safeInterpretations.length > 0 && (
            <button className="secondary-action" type="button" onClick={onClose}>
              بعدا بررسی می‌کنم
            </button>
          )}
        </div>

        {!isJobDone && isJobActive && (
          <section className="job-loading-panel" aria-live="polite">
            <h3>در حال بررسی اطلاعات...</h3>
            <p>لطفاً چند لحظه صبر کنید. نتیجه برای تایید نمایش داده می‌شود.</p>
            {jobError && <div className="observability-error">{jobError}</div>}
          </section>
        )}

        {!isJobDone && isJobActive ? null : shouldShowMultiReview ? (
          <MultiInterpretationReview
            interpretations={safeInterpretations}
            isLoading={isLoading}
            onEdit={(interpretation) => setEditingInterpretationId(interpretation.id)}
            onConfirm={confirmFromReview}
            onDiscard={onDiscard}
          />
        ) : (

        <div className="interpretation-stack">
          {editingInterpretation && safeInterpretations.length > 1 && (
            <div className="multi-edit-toolbar">
              <button type="button" onClick={() => setEditingInterpretationId(null)} disabled={isLoading}>
                بازگشت به فهرست موارد
              </button>
            </div>
          )}
          {visibleInterpretations.map((interpretation) => {
            const kind = getModalKind(interpretation);
            const candidates = candidateMatches(interpretation, safeWorkers);
            const isRole = isRoleAssignment(interpretation);

            // MIXED
            if (kind === "MIXED") {
              return (
                <SplitFlowModal
                  key={interpretation.id}
                  interpretation={interpretation}
                  workers={safeWorkers}
                  activeProjectId={activeProjectId}
                  isLoading={isLoading}
                  onConfirm={(data) => {
                    onConfirmMixed(interpretation, [
                      {
                        ...data.setup,
                        dailyRate: null,
                        notes: null,
                        roleUpdate: data.setup.type,
                      },
                    ], data.financial);
                  }}
                  onDiscard={() => onDiscard(interpretation)}
                />
              );
            }

            // FINANCIAL
            if (kind === "FINANCIAL") {
              return (
                <FinancialModal
                  key={interpretation.id}
                  interpretation={interpretation}
                  workers={safeWorkers}
                  activeProjectId={activeProjectId}
                  projectName={projectName}
                  isLoading={isLoading}
                  onConfirm={(data) => onConfirmFinancialTransaction(interpretation, data)}
                  onDiscard={() => onDiscard(interpretation)}
                />
              );
            }

            // PROFILE
            if (kind === "PROFILE") {
              return (
                <EntityUpdateModal
                  key={interpretation.id}
                  interpretation={interpretation}
                  workers={safeWorkers}
                  activeProjectId={activeProjectId}
                  projectName={projectName}
                  isLoading={isLoading}
                  onConfirm={(data) => onConfirmEntityUpdate(interpretation, data)}
                  onDiscard={() => onDiscard(interpretation)}
                />
              );
            }

            // WORK
            if (kind === "WORK") {
              return (
                <WorkLogModal
                  key={interpretation.id}
                  interpretation={interpretation}
                  workers={safeWorkers}
                  isLoading={isLoading}
                  onConfirm={(payload) => onConfirm(interpretation, payload)}
                  onDiscard={() => onDiscard(interpretation)}
                  onLater={onClose}
                />
              );
            }

            // ROLE_OR_SETUP pre-steps & domain switch
            if (kind === "ROLE_OR_SETUP") {

              // Entity resolution pre-step for unknown entities
              if (candidates.length === 0 && (isUnknownEntity(interpretation) || needsFinancialEntityResolution(interpretation) || needsProfileEntityResolution(interpretation) || interpretation.canonical_event_type === "SETUP_EVENT")) {
                const form = unknownEntityForms[interpretation.id] ?? newEntityForm(interpretation);
                const canContinue = Boolean(form.name.trim() && form.type);
                return (
                  <article className="interpretation-card" key={interpretation.id}>
                    <h3>{unresolvedEntityTitle(interpretation)}</h3>
                    <p className="muted">
                      {interpretation.canonical_event_type === "SETUP_EVENT"
                        ? "این فرد به عنوان شخص جدید در پروژه ثبت می‌شود."
                        : unresolvedEntityHelp(interpretation)}
                    </p>
                    <div className="edit-grid">
                      <label>
                        نام
                        <input
                          value={form.name}
                          onChange={(event) =>
                            setUnknownEntityForms({
                              ...unknownEntityForms,
                              [interpretation.id]: { ...form, name: event.target.value },
                            })
                          }
                        />
                      </label>
                      <label>
                        نقش
                        <select
                          value={form.type}
                          onChange={(event) =>
                            setUnknownEntityForms({
                              ...unknownEntityForms,
                              [interpretation.id]: { ...form, type: event.target.value },
                            })
                          }
                        >
                          {ROLE_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      {shouldShowRoleDetail(form.type) && (
                        <label>
                          تخصص / توضیح نقش
                          <input
                            value={form.roleDetail}
                            onChange={(event) =>
                              setUnknownEntityForms({
                                ...unknownEntityForms,
                                [interpretation.id]: { ...form, roleDetail: event.target.value },
                              })
                            }
                          />
                        </label>
                      )}
                    </div>
                    <div className="modal-actions">
                      <button
                        className="primary-action"
                        type="button"
                        onClick={() => {
                          const entityOverride: EntityOverride = {
                            name: form.name.trim(),
                            type: form.type,
                            roleDetail: form.roleDetail.trim() || null,
                          };
                          const createPayload: ConfirmPayload = {
                            create_new: true,
                            name: entityOverride.name,
                            role: entityOverride.type,
                            role_detail: entityOverride.roleDetail,
                          };
                          if (isRole) {
                            onConfirmRole(interpretation, createPayload, entityOverride);
                          } else {
                            onConfirmCandidate(interpretation, createPayload, entityOverride);
                          }
                        }}
                        disabled={isLoading || !canContinue}
                      >
                        تأیید
                      </button>
                      <button
                        className="danger-action"
                        type="button"
                        onClick={() => onDiscard(interpretation)}
                        disabled={isLoading}
                      >
                        حذف
                      </button>
                    </div>
                  </article>
                );
              }

              // Candidates exist
              if (candidates.length > 0) {
                const selectionValue = candidateSelections[interpretation.id]
                  ?? (isRole && shouldPreferQualifiedRoleCreateNew(entityName(interpretation), candidates)
                    ? "create-new"
                    : String(candidates[0].id));
                const isCreatingNewCandidate = selectionValue === "create-new";
                const selectedCandidate = isCreatingNewCandidate
                  ? undefined
                  : candidates.find((worker) => String(worker.id) === selectionValue) ?? candidates[0];
                const roleEntities = setupEditEntities[interpretation.id] ?? setupEntities(interpretation);
                const editableRoleEntities = roleEntities.length ? roleEntities : setupEntities(interpretation);
                const createForm = unknownEntityForms[interpretation.id] ?? newEntityForm(interpretation);
                const displayedName = isCreatingNewCandidate ? createForm.name : selectedCandidate?.name ?? "";
                const displayedRole = isCreatingNewCandidate
                  ? createForm.type
                  : selectedCandidate?.type ?? preferredEntityType(interpretation);
                const displayedRoleDetail = isCreatingNewCandidate
                  ? createForm.roleDetail
                  : selectedCandidate?.role_detail ?? "";
                const canConfirmCandidate = Boolean(
                  isCreatingNewCandidate ? createForm.name.trim() && createForm.type : selectedCandidate,
                );
                return (
                  <article className="interpretation-card" key={interpretation.id}>
                    <h3>
                      {isRole
                        ? "تعیین نقش فرد"
                        : preferredEntityType(interpretation) === "VENDOR"
                          ? "کدام فروشنده مدنظر است؟"
                          : `«${entityName(interpretation)}» کدام فرد است؟`}
                    </h3>
                    {isRole && <p className="muted">نقش این شخص در پروژه را مشخص کنید</p>}
                    <div className="edit-grid">
                      <label>
                        انتخاب فرد
                        <select
                          value={selectionValue}
                          onChange={(event) =>
                            setCandidateSelections({
                              ...candidateSelections,
                              [interpretation.id]: event.target.value,
                            })
                          }
                        >
                          {candidates.map((worker) => (
                            <option key={worker.id} value={worker.id}>
                              {workerOptionLabel(worker)}
                            </option>
                          ))}
                          <option value="create-new">
                            ایجاد فرد جدید با نام «{entityName(interpretation)}»
                          </option>
                        </select>
                      </label>
                      <label>
                        نام
                        <input
                          value={displayedName}
                          readOnly={!isCreatingNewCandidate}
                          onChange={(event) =>
                            setUnknownEntityForms({
                              ...unknownEntityForms,
                              [interpretation.id]: { ...createForm, name: event.target.value },
                            })
                          }
                        />
                      </label>
                      {isCreatingNewCandidate || isRole ? (
                        <>
                          <label>
                            نقش
                            <select
                              value={isRole && !isCreatingNewCandidate ? (editableRoleEntities[0]?.type ?? displayedRole) : displayedRole}
                              disabled={!isCreatingNewCandidate && !isRole}
                              onChange={(event) => {
                                if (isRole && !isCreatingNewCandidate) {
                                  setSetupEditEntities({
                                    ...setupEditEntities,
                                    [interpretation.id]: editableRoleEntities.map((item, itemIndex) =>
                                      itemIndex === 0 ? { ...item, type: event.target.value } : item,
                                    ),
                                  });
                                } else {
                                  setUnknownEntityForms({
                                    ...unknownEntityForms,
                                    [interpretation.id]: { ...createForm, type: event.target.value },
                                  });
                                }
                              }}
                            >
                              {ROLE_OPTIONS.map((option) => (
                                <option key={option.value} value={option.value}>
                                  {option.label}
                                </option>
                              ))}
                            </select>
                          </label>
                          {shouldShowRoleDetail(displayedRole) && (
                            <label>
                              تخصص / توضیح نقش
                              <input
                                value={displayedRoleDetail}
                                readOnly={!isCreatingNewCandidate}
                                onChange={(event) =>
                                  setUnknownEntityForms({
                                    ...unknownEntityForms,
                                    [interpretation.id]: { ...createForm, roleDetail: event.target.value },
                                  })
                                }
                              />
                            </label>
                          )}
                        </>
                      ) : (
                        <label>
                          نقش فعلی
                          <input
                            value={selectedCandidate ? workerDisplayRole(selectedCandidate) : roleLabelFromType(displayedRole)}
                            readOnly
                          />
                        </label>
                      )}
                    </div>
                    <div className="modal-actions">
                      <button
                        className="primary-action"
                        type="button"
                        onClick={() => {
                          if (isCreatingNewCandidate) {
                            const entityOverride: EntityOverride = {
                              name: createForm.name.trim(),
                              type: createForm.type,
                              roleDetail: createForm.roleDetail.trim() || null,
                            };
                            const createPayload: ConfirmPayload = {
                              create_new: true,
                              name: entityOverride.name,
                              role: entityOverride.type,
                              role_detail: entityOverride.roleDetail,
                            };
                            if (isRole) {
                              onConfirmRole(interpretation, createPayload, entityOverride);
                            } else {
                              onConfirmCandidate(interpretation, createPayload, entityOverride);
                            }
                            return;
                          }
                          if (selectedCandidate) {
                            if (isRole) {
                              onConfirmRole(interpretation, { selected_person_id: selectedCandidate.id });
                            } else {
                              onConfirm(
                                interpretation,
                                interpretation.canonical_event_type === "FINANCIAL_EVENT"
                                  ? { entity_id: selectedCandidate.id, confirmed: true }
                                  : { selected_person_id: selectedCandidate.id },
                              );
                            }
                          }
                        }}
                        disabled={isLoading || !canConfirmCandidate}
                      >
                        تأیید
                      </button>
                      {!isRole && (
                        <button
                          className="danger-action"
                          type="button"
                          onClick={() => onDiscard(interpretation)}
                          disabled={isLoading}
                        >
                          حذف
                        </button>
                      )}
                    </div>
                  </article>
                );
              }

              // Role flow (entity known, no candidates)
              if (isRole) {
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
                            <label>
                              نام
                              <input
                                value={entity.name}
                                onChange={(event) =>
                                  setSetupEditEntities({
                                    ...setupEditEntities,
                                    [interpretation.id]: editableEntities.map((item, itemIndex) =>
                                      itemIndex === index ? { ...item, name: event.target.value } : item,
                                    ),
                                  })
                                }
                              />
                            </label>
                            <label>
                              نقش
                              <select
                                value={entity.type}
                                onChange={(event) =>
                                  setSetupEditEntities({
                                    ...setupEditEntities,
                                    [interpretation.id]: editableEntities.map((item, itemIndex) =>
                                      itemIndex === index ? { ...item, type: event.target.value } : item,
                                    ),
                                  })
                                }
                              >
                                {ROLE_OPTIONS.map((option) => (
                                  <option key={option.value} value={option.value}>
                                    {option.label}
                                  </option>
                                ))}
                              </select>
                            </label>
                            {shouldShowRoleDetail(entity.type) && (
                              <label>
                                تخصص / توضیح نقش
                                <input
                                  value={entity.roleDetail ?? ""}
                                  onChange={(event) =>
                                    setSetupEditEntities({
                                      ...setupEditEntities,
                                      [interpretation.id]: editableEntities.map((item, itemIndex) =>
                                        itemIndex === index ? { ...item, roleDetail: event.target.value } : item,
                                      ),
                                    })
                                  }
                                />
                              </label>
                            )}
                          </div>
                        ))}
                      </div>
                    </section>
                    <div className="modal-actions">
                      <button
                        className="primary-action"
                        type="button"
                        onClick={() => {
                          const entity = editableEntities[0];
                          onConfirmRole(interpretation, {
                            create_new: true,
                            name: entity.name.trim(),
                            role: entity.type,
                            role_detail: entity.roleDetail || null,
                          });
                        }}
                        disabled={isLoading || editableEntities.length === 0 || !editableEntities[0].name.trim()}
                      >
                        تأیید
                      </button>
                    </div>
                  </article>
                );
              }

              // Domain switch for ROLE_OR_SETUP
              switch (interpretation.domain_route?.domain) {
                case "SETUP":
                  return (
                    <SetupModal
                      key={interpretation.id}
                      interpretation={interpretation}
                      workers={safeWorkers}
                      activeProjectId={activeProjectId}
                      projectName={projectName}
                      isLoading={isLoading}
                      onConfirm={(entities) => onConfirmSetupEntities(interpretation, entities)}
                      onDiscard={() => onDiscard(interpretation)}
                    />
                  );
                case "FINANCIAL":
                  return (
                    <FinancialModal
                      key={interpretation.id}
                      interpretation={interpretation}
                      workers={safeWorkers}
                      activeProjectId={activeProjectId}
                      projectName={projectName}
                      isLoading={isLoading}
                      onConfirm={(data) => onConfirmFinancialTransaction(interpretation, data)}
                      onDiscard={() => onDiscard(interpretation)}
                    />
                  );
                case "ENTITY_UPDATE":
                  return (
                    <EntityUpdateModal
                      key={interpretation.id}
                      interpretation={interpretation}
                      workers={safeWorkers}
                      activeProjectId={activeProjectId}
                      projectName={projectName}
                      isLoading={isLoading}
                      onConfirm={(data) => onConfirmEntityUpdate(interpretation, data)}
                      onDiscard={() => onDiscard(interpretation)}
                    />
                  );
                default:
                  return null;
              }
            }

            // NOTE
            if (kind === "NOTE") {
              return (
                <article className="interpretation-card" key={interpretation.id}>
                  <h3>یادداشت</h3>
                  <p>{interpretation.description ?? interpretation.raw_input_text}</p>
                  <div className="modal-actions">
                    <button
                      className="primary-action"
                      type="button"
                      onClick={() => onConfirm(interpretation, { confirmed: true })}
                      disabled={isLoading}
                    >
                      تأیید
                    </button>
                    <button
                      className="danger-action"
                      type="button"
                      onClick={() => onDiscard(interpretation)}
                      disabled={isLoading}
                    >
                      حذف
                    </button>
                  </div>
                </article>
              );
            }

            // UNKNOWN fallback
            return (
              <article className="interpretation-card" key={interpretation.id}>
                <h3>نوع ناشناخته</h3>
                <p className="muted">{interpretation.description ?? interpretation.raw_input_text}</p>
                <div className="modal-actions">
                  <button
                    className="primary-action"
                    type="button"
                    onClick={() => onConfirm(interpretation, { confirmed: true })}
                    disabled={isLoading}
                  >
                    تأیید
                  </button>
                  <button
                    className="danger-action"
                    type="button"
                    onClick={() => onDiscard(interpretation)}
                    disabled={isLoading}
                  >
                    حذف
                  </button>
                </div>
              </article>
            );
          })}
        </div>
        )}
      </section>
    </div>
  );
}
