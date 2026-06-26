import { useState, useMemo } from "react";
import type { PendingInterpretation, Worker } from "../../api";
import { FINANCIAL_DIRECTION_OPTIONS, PAYMENT_METHOD_OPTIONS, ROLE_OPTIONS, SEMANTIC_ACTION_OPTIONS } from "../../constants";
import { exactEntityIdByName } from "../confirmPayload";

const CREATE_NEW_SENTINEL = -1;

function roleLabel(type: string): string {
  if (type === "CLIENT") return "کارفرما";
  if (type === "VENDOR") return "فروشنده";
  if (type === "DAILY_WORKER") return "کارگر";
  if (type === "SKILLED_WORKER") return "استادکار";
  return "سایر";
}

function createNewLabel(name: string, role: string): string {
  const roleMap: Record<string, string> = {
    VENDOR: "فروشنده جدید",
    CLIENT: "کارفرمای جدید",
    DAILY_WORKER: "کارگر روزمزد جدید",
    SKILLED_WORKER: "استادکار جدید",
    OTHER: "شخص جدید",
  };
  return `${name} - ${roleMap[role] || "شخص جدید"}`;
}

function workerLabel(worker: Worker): string {
  return `${worker.name} - ${worker.role_detail?.trim() || roleLabel(worker.type)}`;
}

function entityType(entity: Record<string, unknown>): string {
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

function pickEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  const extracted = (interpretation.extracted_entities ?? [])[0];
  if (extracted) return extracted;
  const structured = interpretation.structured_interpretation as Record<string, unknown> | null;
  if (structured) {
    const siEntities = structured.entities as Array<Record<string, unknown>> | undefined;
    if (Array.isArray(siEntities) && siEntities.length > 0) {
      return siEntities[0];
    }
  }
  return {};
}

function isRoleCompatible(workerType: string, expectedRole: string | null): boolean {
  if (!expectedRole || expectedRole === "OTHER") return true;
  if (expectedRole === "VENDOR" && workerType === "VENDOR") return true;
  if (expectedRole === "CLIENT" && workerType === "CLIENT") return true;
  if (workerType === expectedRole) return true;
  return false;
}

function expectedRole(entity: Record<string, unknown>, semanticAction: string | null, direction: string | null): string | null {
  const role = entity.project_role ?? entity.type;
  if (typeof role === "string" && role) return role;
  if (semanticAction === "PURCHASE_PAID" || semanticAction === "PURCHASE" || semanticAction === "PURCHASE_UNPAID") return "VENDOR";
  if (direction === "INCOMING") return "CLIENT";
  return null;
}

function actionLabel(action: string | null): string {
  const option = SEMANTIC_ACTION_OPTIONS.find((item) => item.value === action);
  if (option) return option.label;
  if (action === "PAYMENT_IN") return "دریافتی";
  if (action === "PAYMENT_OUT") return "پرداختی";
  return "رویداد مالی";
}

interface FinancialModalProps {
  interpretation: PendingInterpretation;
  workers: Worker[];
  activeProjectId: number | null;
  projectName?: string | null;
  isLoading: boolean;
  onConfirm: (data: {
    entity_id?: number | null;
    amount: string;
    direction: string;
    payment_method: string;
    description?: string | null;
    due_date?: string | null;
    create_new_entity?: boolean;
    entity_name?: string;
    project_role?: string;
  }) => void;
  onDiscard: () => void;
}

export function FinancialModal({
  interpretation,
  workers,
  activeProjectId,
  projectName,
  isLoading,
  onConfirm,
  onDiscard,
}: FinancialModalProps) {
  const extractedCounterparty = useMemo(() => pickEntity(interpretation), [interpretation]);

  const resolvedEntityId = useMemo(() => {
    if (interpretation.suggested_entity_id) return interpretation.suggested_entity_id;

    const candidates = extractedCounterparty.candidate_matches;
    const candidateList = Array.isArray(candidates) ? candidates : [];
    const entityName = typeof extractedCounterparty.name === "string" ? extractedCounterparty.name.trim() : "";
    const direction = interpretation.financial_direction ?? null;
    const semAction = interpretation.semantic_action ?? null;
    const expRole = expectedRole(extractedCounterparty, semAction, direction);
    const clients = workers.filter((w) => w.type === "CLIENT");

    // 1. unique normalized project-person match, even if extraction guessed a generic vendor role
    const normalizedNameMatch = entityName ? exactEntityIdByName(entityName, workers) : null;
    if (normalizedNameMatch) return normalizedNameMatch;

    // 2. exact match + role compatible
    for (const c of candidateList) {
      const rec = c as Record<string, unknown>;
      if (rec.match_type === "exact" && typeof rec.person_id === "number") {
        const worker = workers.find((w) => w.id === rec.person_id);
        if (worker && isRoleCompatible(worker.type, expRole)) return worker.id;
      }
    }

    // 3. single role-compatible partial >= 0.75
    const viable: { worker: Worker; score: number }[] = [];
    for (const c of candidateList) {
      const rec = c as Record<string, unknown>;
      if (typeof rec.person_id !== "number") continue;
      const score = typeof rec.score === "number" ? rec.score : 0;
      if (score <= 0) continue;
      const worker = workers.find((w) => w.id === rec.person_id);
      if (worker && isRoleCompatible(worker.type, expRole)) viable.push({ worker, score });
    }
    if (viable.length === 1 && viable[0].score >= 0.75) return viable[0].worker.id;

    // 4. CLIENT rule: partial >= 0.60 when exactly one project client
    if (expRole === "CLIENT" && clients.length === 1) {
      const client = clients[0];
      const inCandidates = candidateList.some((c) => (c as Record<string, unknown>).person_id === client.id);
      if (inCandidates) return client.id;
    }

    // 5. exact name match (role-compatible)
    if (entityName) {
      const match = workers.find((w) => w.name === entityName && isRoleCompatible(w.type, expRole));
      if (match) return match.id;
    }

    return null;
  }, [interpretation.suggested_entity_id, interpretation.financial_direction, interpretation.semantic_action, extractedCounterparty, workers]);

  const extractedName = useMemo(
    () => (typeof extractedCounterparty.name === "string" ? extractedCounterparty.name.trim() : ""),
    [extractedCounterparty.name],
  );

  const extractedType = useMemo(() => entityType(extractedCounterparty), [extractedCounterparty]);

  const showCreateNew = !resolvedEntityId && extractedName.length > 0;

  const [entityId, setEntityId] = useState<number | null>(() =>
    showCreateNew ? CREATE_NEW_SENTINEL : resolvedEntityId,
  );

  const [amount, setAmount] = useState(interpretation.extracted_amount ?? "");
  const [direction, setDirection] = useState(interpretation.financial_direction ?? "");
  const [paymentMethod, setPaymentMethod] = useState(interpretation.payment_method ?? "");
  const [newEntityName, setNewEntityName] = useState(extractedName);
  const [newEntityRole, setNewEntityRole] = useState(extractedType);
  const [description, setDescription] = useState(interpretation.description ?? interpretation.matched_input_text ?? "");
  const [dueDate, setDueDate] = useState(interpretation.due_date ?? "");

  const isCreatingNew = entityId === CREATE_NEW_SENTINEL;

  function handleConfirm() {
    if (isCreatingNew) {
      onConfirm({
        entity_id: null,
        amount: amount.trim(),
        direction,
        payment_method: paymentMethod,
        description: description.trim() || null,
        due_date: dueDate.trim() || null,
        create_new_entity: true,
        entity_name: newEntityName.trim(),
        project_role: newEntityRole,
      });
    } else if (entityId) {
      onConfirm({
        entity_id: entityId,
        amount: amount.trim(),
        direction,
        payment_method: paymentMethod,
        description: description.trim() || null,
        due_date: dueDate.trim() || null,
      });
    }
  }

  const canConfirm = isCreatingNew
    ? Boolean(newEntityName.trim() && newEntityRole && amount.trim())
    : Boolean(entityId && amount.trim());

  const workerOptions = workers;

  return (
    <article className="interpretation-card">
      <section className="approval-section">
        <span className="eyebrow">برداشت مالی</span>
        <div className="edit-grid">
          <label>
            نوع ثبت
            <input value={actionLabel(interpretation.semantic_action)} readOnly />
          </label>
          <label>
            طرف حساب
            <select
              value={isCreatingNew ? CREATE_NEW_SENTINEL : (entityId ?? "")}
              onChange={(e) => {
                const val = e.target.value;
                if (val === String(CREATE_NEW_SENTINEL)) {
                  setEntityId(CREATE_NEW_SENTINEL);
                } else {
                  setEntityId(val ? Number(val) : null);
                }
              }}
            >
              <option value="">انتخاب کنید...</option>
              {workerOptions.map((w) => (
                <option key={w.id} value={w.id}>{workerLabel(w)}</option>
              ))}
              {showCreateNew && (
                <option value={CREATE_NEW_SENTINEL}>
                  {createNewLabel(extractedName, extractedType)}
                </option>
              )}
            </select>
          </label>
          {isCreatingNew && (
            <>
              <label>
                نام طرف حساب جدید
                <input
                  value={newEntityName}
                  onChange={(e) => setNewEntityName(e.target.value)}
                />
              </label>
              <label>
                نقش
                <select
                  value={newEntityRole}
                  onChange={(e) => setNewEntityRole(e.target.value)}
                >
                  {ROLE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </label>
            </>
          )}
          <label>
            مبلغ
            <input value={amount} onChange={(e) => setAmount(e.target.value)} />
          </label>
          <label>
            جهت مالی
            <select value={direction} onChange={(e) => setDirection(e.target.value)}>
              {FINANCIAL_DIRECTION_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
          <label>
            روش پرداخت
            <select value={paymentMethod} onChange={(e) => setPaymentMethod(e.target.value)}>
              {PAYMENT_METHOD_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
          <label>
            توضیحات
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          {interpretation.due_date && (
            <label>
              سررسید
              <input value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
            </label>
          )}
          <label>
            پروژه
            <input value={projectName || (activeProjectId ? `پروژه ${activeProjectId}` : "ثبت نشده")} readOnly />
          </label>
        </div>
      </section>
      <div className="modal-actions">
        <button
          className="primary-action"
          type="button"
          onClick={handleConfirm}
          disabled={isLoading || !canConfirm}
        >
          تایید و ثبت
        </button>
        <button className="danger-action" type="button" onClick={onDiscard} disabled={isLoading}>
          نادیده گرفتن
        </button>
      </div>
    </article>
  );
}
