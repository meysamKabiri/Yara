import { useEffect, useRef, useState } from "react";
import { X } from "lucide-react";
import type { JobEvent, JobState, PendingInterpretation, ProjectTaskCreatePayload, Worker } from "../api";
import type { SetupEntity } from "../types/domain";
import { SetupModal } from "./setup/SetupModal";
import { FinancialModal } from "./financial/FinancialModal";
import { EntityUpdateModal } from "./entity/EntityUpdateModal";
import { SplitFlowModal } from "./split/SplitFlowModal";
import { exactEntityIdByName } from "./confirmPayload";
import {
  MULTI_ACTION_WARNING,
  UNCERTAIN_INTERPRETATION_MESSAGE,
  interpretationText,
  isUncertainInterpretation,
  looksLikeMultiAction,
  moneyWithUnit,
} from "./betaSafety";

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

type ModalKind = "MIXED" | "FINANCIAL" | "PROFILE" | "TASK" | "SETUP" | "NOTE" | "UNKNOWN";

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

  onConfirm: (interpretation: PendingInterpretation, payload?: ConfirmPayload) => Promise<void>;
  onConfirmTask: (interpretation: PendingInterpretation, payload: ProjectTaskCreatePayload) => Promise<void>;
  onDiscard: (interpretation: PendingInterpretation) => Promise<void>;

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

function getModalKind(interpretation: PendingInterpretation): ModalKind {
  switch (interpretation.domain_route?.ui_mode) {
    case "TaskDashboard":
      return "TASK";
    case "FinancialModal":
      return "FINANCIAL";
    case "SetupModal":
      return "SETUP";
    case "EntityUpdateModal":
      return "PROFILE";
    case "SplitFlow":
      return "MIXED";
    case "NoteFallback":
      return "NOTE";
  }
  return "UNKNOWN";
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
  return moneyWithUnit(value);
}

function workerOptionLabel(worker: Worker): string {
  return worker.role_detail?.trim() ? `${worker.name} - ${worker.role_detail.trim()}` : worker.name;
}

function workWorkerId(interpretation: PendingInterpretation, workers: Worker[]): number | null {
  if (interpretation.suggested_entity_id) return interpretation.suggested_entity_id;
  const name = entityName(interpretation);
  if (!name || isUnknownEntity(interpretation)) return null;
  return exactEntityIdByName(name, workers);
}

function dateValue(value: unknown): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const nested = (value as Record<string, unknown>).value;
    if (typeof nested === "string" && nested.trim()) return nested.trim();
  }
  return "";
}

function localIsoDate(offsetDays = 0): string {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function taskDueDateFromSignals(interpretation: PendingInterpretation): string {
  const explanation = interpretation.semantic_explanation && typeof interpretation.semantic_explanation === "object"
    ? interpretation.semantic_explanation as Record<string, unknown>
    : {};
  const matchedSignals = Array.isArray(explanation.matched_signals)
    ? explanation.matched_signals.map((signal) => String(signal))
    : [];
  const signalText = [
    ...matchedSignals,
    interpretation.raw_input_text,
    interpretation.matched_input_text ?? "",
    interpretation.description ?? "",
  ].join(" ");
  if (signalText.includes("پس فردا") || signalText.includes("پسفردا") || signalText.includes("day_after_tomorrow")) {
    return localIsoDate(2);
  }
  if (signalText.includes("فردا") || signalText.includes("tomorrow")) {
    return localIsoDate(1);
  }
  if (signalText.includes("امروز") || signalText.includes("today")) {
    return localIsoDate(0);
  }
  return "";
}

function taskModalDueDate(interpretation: PendingInterpretation): string {
  const structured = interpretation.structured_interpretation && typeof interpretation.structured_interpretation === "object"
    ? interpretation.structured_interpretation as Record<string, unknown>
    : {};
  const finalTask = structured.final_task_object && typeof structured.final_task_object === "object"
    ? structured.final_task_object as Record<string, unknown>
    : {};
  const task = structured.task && typeof structured.task === "object"
    ? structured.task as Record<string, unknown>
    : {};
  return (
    dateValue(finalTask.due_date) ||
    dateValue(structured.due_date) ||
    dateValue(task.due_date) ||
    dateValue(interpretation.due_date) ||
    taskDueDateFromSignals(interpretation)
  );
}

function TaskModal({
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
  onConfirm: (payload: ProjectTaskCreatePayload) => void;
  onDiscard: () => void;
  onLater?: () => void;
}) {
  const initialWorkerId = workWorkerId(interpretation, workers);
  const initialWorkerChoice = initialWorkerId ? String(initialWorkerId) : "";
  const initialTitle = interpretation.description ?? interpretation.matched_input_text ?? interpretation.raw_input_text;
  const hydratedDueDate = taskModalDueDate(interpretation);
  const [workerChoice, setWorkerChoice] = useState(initialWorkerChoice);
  const [title, setTitle] = useState(initialTitle);
  const [dueDate, setDueDate] = useState(hydratedDueDate);
  const selectedWorker = workers.find((worker) => String(worker.id) === workerChoice);
  const canConfirm = title.trim().length > 0;

  useEffect(() => {
    setWorkerChoice(initialWorkerChoice);
    setTitle(initialTitle);
    setDueDate(hydratedDueDate);
  }, [interpretation.id, initialWorkerChoice, initialTitle, hydratedDueDate]);

  function submit() {
    onConfirm({
      title: title.trim(),
      raw_text: interpretation.raw_input_text,
      assign_to_person: Boolean(selectedWorker),
      assignee_id: selectedWorker?.id ?? null,
      due_date: dueDate || null,
    });
  }

  return (
    <article className="interpretation-card modal-shell">
      <header className="modal-header">
        <div>
          <h3 className="modal-title">ثبت کار</h3>
          <p>{interpretation.matched_input_text || interpretation.raw_input_text}</p>
        </div>
      </header>
      <div className="modal-body">
        {isUncertainInterpretation(interpretation) && <p className="warning-text">{UNCERTAIN_INTERPRETATION_MESSAGE}</p>}
        {looksLikeMultiAction(reviewText(interpretation)) && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
        <div className="confirmation-summary">
          <p><strong>نوع عملیات:</strong> ایجاد کار قابل پیگیری</p>
          <p><strong>مسئول پیشنهادی:</strong> {selectedWorker?.name ?? entityName(interpretation)}</p>
          <p><strong>اثر بعد از تأیید:</strong> <span className="impact-text">یک کار در داشبورد کارها ساخته می‌شود.</span></p>
          <p>قبل از تأیید می‌توانید عنوان، مسئول و زمان انجام را اصلاح کنید.</p>
        </div>
        <div className="edit-grid">
        <label className="wide-field">
          عنوان کار
          <textarea value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label>
          مسئول
          <select value={workerChoice} onChange={(event) => setWorkerChoice(event.target.value)}>
            <option value="">بدون مسئول</option>
            {workers.map((worker) => (
              <option key={worker.id} value={worker.id}>
                {workerOptionLabel(worker)}
              </option>
            ))}
          </select>
        </label>
        <label>
          زمان انجام
          <input type="date" value={dueDate} onChange={(event) => setDueDate(event.target.value)} />
        </label>
        </div>
      </div>
      <div className="modal-footer">
        <div className="modal-actions">
          <button className="primary-action" type="button" onClick={submit} disabled={isLoading || !canConfirm}>
            تأیید و ثبت
          </button>
          <button type="button" onClick={onLater ?? onDiscard} disabled={isLoading}>
            بعدا بررسی می‌کنم
          </button>
          <button className="danger-action" type="button" onClick={onDiscard} disabled={isLoading}>
            رد کردن
          </button>
        </div>
      </div>
    </article>
  );
}



function interpretationLabel(interpretation: PendingInterpretation): string {
  switch (getModalKind(interpretation)) {
    case "TASK":
      return "ایجاد کار قابل پیگیری";
    case "FINANCIAL":
      return "رویداد مالی";
    case "SETUP":
      return "تعریف طرف حساب";
    case "PROFILE":
      return "به‌روزرسانی اطلاعات فرد";
    case "MIXED":
      return "چند عملیات";
    case "NOTE":
      return "یادداشت";
    default:
      return "مورد پیشنهادی";
  }
}

function reviewText(interpretation: PendingInterpretation): string {
  return interpretationText(interpretation);
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
    isUncertainInterpretation(interpretation) ||
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
          const multiActionWarning = looksLikeMultiAction(reviewText(interpretation));
          return (
            <article className="multi-review-card" key={interpretation.id}>
              <div className="multi-review-card-main">
                <strong>
                  {interpretationLabel(interpretation)}
                  {warning && <span className="warning-dot" title="نیاز به بررسی">●</span>}
                </strong>
                <p className="review-text-preview">{reviewText(interpretation)}</p>
                {warning && <p className="warning-text">{UNCERTAIN_INTERPRETATION_MESSAGE}</p>}
                {multiActionWarning && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
                <dl className="multi-review-meta">
                  {interpretation.extracted_amount && (
                    <>
                      <dt>مبلغ</dt>
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
                  تأیید و ثبت
                </button>
                <button type="button" onClick={() => onEdit(interpretation)} disabled={isLoading}>
                  ویرایش
                </button>
                <button className="danger-action" type="button" onClick={() => onDiscard(interpretation)} disabled={isLoading}>
                  رد کردن
                </button>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
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
  onConfirm,
  onConfirmTask,
  onDiscard,
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
      const exactEntityId = exactWorkerIdForProfile(interpretation, safeWorkers);
      onConfirmEntityUpdate(interpretation, {
        entityId: exactEntityId,
        name: entityName(interpretation),
        phone: textValue(updates.phone ?? entity.phone),
        accountNumber: textValue(updates.account_number ?? entity.account_number),
        dailyRate: textValue(updates.daily_rate ?? entity.daily_rate),
        role: preferredEntityType(interpretation),
        roleDetail: textValue(updates.role_detail ?? entity.role_detail),
        create_new_entity: !exactEntityId && !isUnknownEntity(interpretation),
        entity_name: entityName(interpretation),
        project_role: preferredEntityType(interpretation),
        field_updates: updates,
      });
      return;
    }
    if (kind === "TASK") {
      const assigneeId = workWorkerId(interpretation, safeWorkers);
      onConfirmTask(interpretation, {
        title: interpretation.description ?? interpretation.matched_input_text ?? interpretation.raw_input_text,
        raw_text: interpretation.raw_input_text,
        assign_to_person: Boolean(assigneeId),
        assignee_id: assigneeId,
        due_date: taskModalDueDate(interpretation) || null,
      });
      return;
    }
    if (kind === "SETUP") {
      onConfirmSetupEntities(interpretation, setupEntities(interpretation));
      return;
    }
    onConfirm(interpretation, { confirmed: true });
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="interpretation-title">
      <section className="confirmation-modal modal-shell">
        <div className="modal-header">
          <div>
            <span className="eyebrow">بررسی</span>
            {safeInterpretations.length > 1 ? (
              <>
                <h2 id="interpretation-title">بررسی موارد استخراج‌شده</h2>
                <p>موارد استخراج‌شده را تایید یا ویرایش کنید.</p>
              </>
            ) : safeInterpretations.length === 1 ? (
              <>
                <h2 id="interpretation-title">بررسی اطلاعات</h2>
                <p>اگر درست است تأیید کنید، اگر نه اصلاح کنید.</p>
              </>
            ) : (
              <>
                <h2 id="interpretation-title">درخواست شما در صف پردازش است</h2>
                <p>یارا در حال بررسی متن شماست...</p>
              </>
            )}
          </div>
          {onClose && safeInterpretations.length > 0 && (
            <button className="modal-close icon-button" type="button" onClick={onClose} aria-label="بستن">
              <X aria-hidden="true" size={20} />
            </button>
          )}
        </div>

        <div className="modal-body">
          {!isJobDone && isJobActive && (
            <section className="job-loading-panel" aria-live="polite">
              <h3>یارا در حال بررسی متن شماست...</h3>
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
            const multiActionWarning = looksLikeMultiAction(reviewText(interpretation));
            const uncertaintyWarning = isUncertainInterpretation(interpretation);
            const safetyWarnings = (
              <>
                {uncertaintyWarning && <p className="warning-text">{UNCERTAIN_INTERPRETATION_MESSAGE}</p>}
                {multiActionWarning && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
              </>
            );

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
                  showHeader={false}
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

            // TASK
            if (kind === "TASK") {
              return (
                <TaskModal
                  key={interpretation.id}
                  interpretation={interpretation}
                  workers={safeWorkers}
                  isLoading={isLoading}
                  onConfirm={(payload) => onConfirmTask(interpretation, payload)}
                  onDiscard={() => onDiscard(interpretation)}
                  onLater={onClose}
                />
              );
            }

            // SETUP
            if (kind === "SETUP") {
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
            }

            // NOTE
            if (kind === "NOTE") {
              return (
                <article className="interpretation-card modal-shell" key={interpretation.id}>
                  <header className="modal-header">
                    <div>
                      <h3 className="modal-title">یادداشت</h3>
                      <p>برداشت سیستم از این متن قطعی نیست. لطفاً اطلاعات را بررسی یا اصلاح کنید.</p>
                    </div>
                  </header>
                  <div className="modal-body">
                    {multiActionWarning && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
                    <div className="confirmation-summary">
                      <p><strong>نوع عملیات:</strong> یادداشت / سایر</p>
                      <p><strong>برداشت سیستم از متن شما:</strong> {interpretation.description ?? interpretation.raw_input_text}</p>
                      <p><strong>اثر بعد از تأیید:</strong> <span className="impact-text">این ثبت موجودی مالی پروژه را تغییر نمی‌دهد.</span></p>
                    </div>
                  </div>
                  <div className="modal-footer">
                    <div className="modal-actions">
                      <button
                        className="primary-action"
                        type="button"
                        onClick={() => onConfirm(interpretation, { confirmed: true })}
                        disabled={isLoading}
                      >
                        تأیید و ثبت
                      </button>
                      <button
                        className="danger-action"
                        type="button"
                        onClick={() => onDiscard(interpretation)}
                        disabled={isLoading}
                      >
                        رد کردن
                      </button>
                    </div>
                  </div>
                </article>
              );
            }

            // UNKNOWN fallback
            return (
              <article className="interpretation-card modal-shell" key={interpretation.id}>
                <header className="modal-header">
                  <div>
                    <h3 className="modal-title">نوع ناشناخته</h3>
                    <p>برداشت سیستم از این متن قطعی نیست. لطفاً اطلاعات را بررسی یا اصلاح کنید.</p>
                  </div>
                </header>
                <div className="modal-body">
                  {multiActionWarning && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
                  <div className="confirmation-summary">
                    <p><strong>برداشت سیستم از متن شما:</strong> {interpretation.description ?? interpretation.raw_input_text}</p>
                    <p><strong>اثر بعد از تأیید:</strong> <span className="impact-text">این ثبت موجودی مالی پروژه را تغییر نمی‌دهد.</span></p>
                  </div>
                </div>
                <div className="modal-footer">
                  <div className="modal-actions">
                    <button
                      className="primary-action"
                      type="button"
                      onClick={() => onConfirm(interpretation, { confirmed: true })}
                      disabled={isLoading}
                    >
                      تأیید و ثبت
                    </button>
                    <button
                      className="danger-action"
                      type="button"
                      onClick={() => onDiscard(interpretation)}
                      disabled={isLoading}
                    >
                      رد کردن
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
          </div>
          )}
        </div>
      </section>
    </div>
  );
}
