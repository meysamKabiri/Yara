import { useState, useMemo } from "react";
import type { PendingInterpretation, Worker } from "../../api";
import { ROLE_OPTIONS } from "../../constants";

const CREATE_NEW_SENTINEL = -1;

function roleLabelFromType(type: string | undefined): string {
  if (type === "CLIENT") return "کارفرما";
  if (type === "VENDOR") return "فروشنده";
  if (type === "SKILLED_WORKER") return "استادکار";
  if (type === "DAILY_WORKER") return "کارگر";
  if (type === "OTHER") return "سایر";
  return "فرد";
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
  const detail = worker.role_detail?.trim();
  return `${worker.name} - ${detail || roleLabelFromType(worker.type)}`;
}

function candidateIds(interpretation: PendingInterpretation): number[] {
  const entity = (interpretation.extracted_entities ?? [])[0] ?? {};
  const structured = firstStructuredEntity(interpretation);
  const candidates = entity.candidate_matches ?? structured.candidate_matches;
  if (!Array.isArray(candidates)) return [];
  return candidates
    .map((candidate) => {
      if (typeof candidate !== "object" || candidate === null) return null;
      const record = candidate as Record<string, unknown>;
      const id = record.person_id ?? record.worker_id;
      return typeof id === "number" ? id : Number(id);
    })
    .filter((id): id is number => Number.isFinite(id));
}

function textValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number") return String(value);
  return null;
}

function firstNonEmpty(...values: unknown[]): unknown {
  for (const value of values) {
    if (textValue(value) !== null) return value;
  }
  return undefined;
}

function firstStructuredEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  const si = interpretation.structured_interpretation as Record<string, unknown> | null;
  const entities = Array.isArray(si?.entities) ? si.entities : [];
  const entity = entities.find((item) => typeof item === "object" && item !== null);
  return entity as Record<string, unknown> | undefined ?? {};
}

type EntityUpdateVariant = "PHONE_UPDATE" | "ACCOUNT_UPDATE" | "DAILY_RATE_UPDATE" | "NOTES_UPDATE" | "GENERAL_PROFILE_UPDATE";

function detectVariant(entity: Record<string, unknown>, updates: Record<string, unknown>): EntityUpdateVariant {
  const hasPhone = textValue(updates.phone ?? entity.phone) !== null;
  const hasAccount = textValue(
    updates.account_number ?? updates.accountNumber ??
    updates.card_number ?? updates.cardNumber ??
    updates.sheba ?? updates.iban ??
    entity.account_number ?? entity.accountNumber ??
    entity.card_number ?? entity.cardNumber ??
    entity.sheba ?? entity.iban
  ) !== null;
  const hasDailyRate = textValue(updates.daily_rate ?? updates.dailyRate ?? entity.daily_rate ?? entity.dailyRate) !== null;
  const hasNotes = textValue(updates.notes ?? entity.notes) !== null;

  const present = [hasPhone, hasAccount, hasDailyRate, hasNotes].filter(Boolean).length;
  if (present > 1) return "GENERAL_PROFILE_UPDATE";
  if (hasPhone) return "PHONE_UPDATE";
  if (hasAccount) return "ACCOUNT_UPDATE";
  if (hasDailyRate) return "DAILY_RATE_UPDATE";
  if (hasNotes) return "NOTES_UPDATE";
  return "GENERAL_PROFILE_UPDATE";
}

function shouldShowRoleDetail(type: string): boolean {
  return type === "SKILLED_WORKER" || type === "OTHER";
}

function mergedEntityForUpdate(interpretation: PendingInterpretation): Record<string, unknown> {
  const extracted = (interpretation.extracted_entities ?? [])[0] ?? {};
  const structured = firstStructuredEntity(interpretation);
  const extractedUpdates = typeof extracted.field_updates === "object" && extracted.field_updates !== null
    ? extracted.field_updates as Record<string, unknown>
    : {};
  const structuredUpdates = typeof structured.field_updates === "object" && structured.field_updates !== null
    ? structured.field_updates as Record<string, unknown>
    : {};

  const role = firstNonEmpty(structured.project_role, structured.type) ?? firstNonEmpty(extracted.project_role, extracted.type) ?? "OTHER";

  return {
    ...structured,
    ...extracted,
    project_role: role,
    type: role,
    field_updates: {
      ...structuredUpdates,
      ...extractedUpdates,
      phone: firstNonEmpty(extractedUpdates.phone, structuredUpdates.phone),
      account_number: firstNonEmpty(
        extractedUpdates.account_number,
        extractedUpdates.accountNumber,
        structuredUpdates.account_number,
        structuredUpdates.accountNumber,
      ),
      daily_rate: firstNonEmpty(
        extractedUpdates.daily_rate,
        extractedUpdates.dailyRate,
        structuredUpdates.daily_rate,
        structuredUpdates.dailyRate,
      ),
      notes: firstNonEmpty(
        extractedUpdates.notes,
        structuredUpdates.notes,
      ),
      role_detail: firstNonEmpty(
        extractedUpdates.role_detail,
        extractedUpdates.roleDetail,
        structuredUpdates.role_detail,
        structuredUpdates.roleDetail,
      ),
    },
    name: firstNonEmpty(extracted.name, structured.name) ?? extracted.name ?? structured.name,
    phone: firstNonEmpty(extracted.phone, structured.phone),
    account_number: firstNonEmpty(
      extracted.account_number,
      extracted.accountNumber,
      structured.account_number,
      structured.accountNumber,
    ),
  };
}

interface EntityUpdateModalProps {
  interpretation: PendingInterpretation;
  workers: Worker[];
  activeProjectId: number | null;
  projectName?: string | null;
  isLoading: boolean;
  onConfirm: (data: {
    entityId?: number | null;
    name: string;
    phone: string | null;
    accountNumber: string | null;
    dailyRate: string | null;
    role: string;
    roleDetail: string | null;
    create_new_entity?: boolean;
    entity_name?: string;
    project_role?: string;
    field_updates?: Record<string, unknown>;
  }) => void;
  onDiscard: () => void;
}

export function EntityUpdateModal({
  interpretation,
  workers,
  activeProjectId,
  projectName,
  isLoading,
  onConfirm,
  onDiscard,
}: EntityUpdateModalProps) {
  const entity = mergedEntityForUpdate(interpretation);
  const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
    ? entity.field_updates as Record<string, unknown>
    : {};

  const candidates = candidateIds(interpretation)
    .map((id) => workers.find((worker) => worker.id === id))
    .filter((worker): worker is Worker => Boolean(worker));
  const personOptions = candidates.length ? candidates : workers;
  const initialEntityId = interpretation.suggested_entity_id
    ?? candidates[0]?.id
    ?? null;

  const extractedName = textValue(entity.name) ?? "";
  const extractedRole = textValue(entity.project_role ?? entity.type) ?? "DAILY_WORKER";

  const hasExisting = initialEntityId !== null;
  const showCreateNew = !hasExisting && extractedName.length > 0;

  const selectedPerson = initialEntityId
    ? workers.find((w) => w.id === initialEntityId)
    : null;

  const variant = detectVariant(entity, updates);

  const hasPhoneUpdate = textValue(updates.phone ?? entity.phone) !== null;
  const hasAccountUpdate = textValue(
    updates.account_number ?? updates.accountNumber ??
    updates.card_number ?? updates.cardNumber ??
    updates.sheba ?? updates.iban ??
    entity.account_number ?? entity.accountNumber ??
    entity.card_number ?? entity.cardNumber ??
    entity.sheba ?? entity.iban
  ) !== null;
  const hasDailyRateUpdate = textValue(updates.daily_rate ?? updates.dailyRate ?? entity.daily_rate ?? entity.dailyRate) !== null;
  const hasNotesUpdate = textValue(updates.notes ?? entity.notes) !== null;
  const hasRoleDetailUpdate = Boolean(
    textValue(updates.role_detail ?? entity.role_detail)
    || interpretation.semantic_action === "SET_ROLE"
  );

  const initialName = selectedPerson?.name ?? extractedName;
  const initialRole = selectedPerson?.type ?? extractedRole;
  const initialRoleDetail = selectedPerson?.role_detail ?? "";
  const initialPhone = hasPhoneUpdate
    ? (textValue(updates.phone ?? entity.phone) ?? selectedPerson?.phone ?? "")
    : (selectedPerson?.phone ?? "");
  const initialAccountNumber = hasAccountUpdate
    ? (textValue(updates.account_number ?? updates.accountNumber ?? entity.account_number ?? entity.accountNumber) ?? selectedPerson?.account_number ?? "")
    : (selectedPerson?.account_number ?? "");
  const initialDailyRate = hasDailyRateUpdate
    ? (textValue(updates.daily_rate ?? updates.dailyRate ?? entity.daily_rate ?? entity.dailyRate) ?? selectedPerson?.daily_rate ?? "")
    : (selectedPerson?.daily_rate ?? "");
  const initialNotes = hasNotesUpdate
    ? (textValue(updates.notes ?? entity.notes) ?? selectedPerson?.notes ?? "")
    : (selectedPerson?.notes ?? "");

  const [entityId, setEntityId] = useState<number | null>(showCreateNew ? CREATE_NEW_SENTINEL : initialEntityId);
  const [name, setName] = useState(initialName);
  const [role, setRole] = useState(initialRole);
  const [roleDetail, setRoleDetail] = useState(initialRoleDetail);
  const [phone, setPhone] = useState(initialPhone);
  const [accountNumber, setAccountNumber] = useState(initialAccountNumber);
  const [dailyRate, setDailyRate] = useState(initialDailyRate);
  const [notes, setNotes] = useState(initialNotes);

  const isCreatingNew = entityId === CREATE_NEW_SENTINEL;

  const showPhone = variant === "PHONE_UPDATE" || (variant === "GENERAL_PROFILE_UPDATE" && hasPhoneUpdate);
  const showAccount = variant === "ACCOUNT_UPDATE" || (variant === "GENERAL_PROFILE_UPDATE" && hasAccountUpdate);
  const showDailyRate = variant === "DAILY_RATE_UPDATE" || (variant === "GENERAL_PROFILE_UPDATE" && hasDailyRateUpdate);
  const showNotes = variant === "NOTES_UPDATE";
  const showRoleDetail = variant === "GENERAL_PROFILE_UPDATE" && hasRoleDetailUpdate;
  const isRoleReadOnly = variant !== "GENERAL_PROFILE_UPDATE" && !isCreatingNew;

  function handleConfirm() {
    if (isCreatingNew) {
      const updates: Record<string, unknown> = {};
      if (phone.trim()) updates.phone = phone.trim();
      if (accountNumber.trim()) updates.account_number = accountNumber.trim();
      if (dailyRate.trim()) updates.daily_rate = dailyRate.trim();
      if (roleDetail.trim()) updates.role_detail = roleDetail.trim();
      onConfirm({
        entityId: null,
        name: name.trim(),
        phone: showPhone ? (phone.trim() || null) : null,
        accountNumber: showAccount ? (accountNumber.trim() || null) : null,
        dailyRate: showDailyRate ? (dailyRate.trim() || null) : null,
        role,
        roleDetail: showRoleDetail ? (shouldShowRoleDetail(role) ? roleDetail.trim() || null : null) : null,
        create_new_entity: true,
        entity_name: name.trim(),
        project_role: role,
        field_updates: Object.keys(updates).length > 0 ? updates : undefined,
      });
    } else if (entityId) {
      onConfirm({
        entityId,
        name: name.trim(),
        phone: showPhone ? (phone.trim() || null) : null,
        accountNumber: showAccount ? (accountNumber.trim() || null) : null,
        dailyRate: showDailyRate ? (dailyRate.trim() || null) : null,
        role,
        roleDetail: showRoleDetail ? (shouldShowRoleDetail(role) ? roleDetail.trim() || null : null) : null,
      });
    }
  }

  const canConfirm = isCreatingNew
    ? Boolean(name.trim() && role)
    : Boolean(entityId && name.trim());

  return (
    <article className="interpretation-card">
      <section className="approval-section">
        <span className="eyebrow">به‌روزرسانی اطلاعات فرد</span>
        <div className="setup-edit-list">
          <div className="setup-edit-row">
            <label>
              فرد
              <select
                value={isCreatingNew ? CREATE_NEW_SENTINEL : (entityId ?? "")}
                onChange={(e) => {
                  const val = e.target.value;
                  if (val === String(CREATE_NEW_SENTINEL)) {
                    setEntityId(CREATE_NEW_SENTINEL);
                    setName(extractedName);
                    setRole(extractedRole);
                    setRoleDetail("");
                    setPhone(textValue(updates.phone ?? entity.phone) ?? "");
                    setAccountNumber(textValue(updates.account_number ?? updates.accountNumber ?? entity.account_number ?? entity.accountNumber) ?? "");
                    setDailyRate(textValue(updates.daily_rate ?? updates.dailyRate ?? entity.daily_rate ?? entity.dailyRate) ?? "");
                    setNotes(textValue(updates.notes ?? entity.notes) ?? "");
                  } else {
                    const nextId = val ? Number(val) : null;
                    setEntityId(nextId);
                    const selected = workers.find((worker) => worker.id === nextId);
                    if (selected) {
                      setName(selected.name);
                      setRole(selected.type);
                      setRoleDetail(selected.role_detail ?? "");
                      setPhone(
                        textValue(updates.phone ?? entity.phone) ?? selected.phone ?? ""
                      );
                      setAccountNumber(
                        textValue(updates.account_number ?? updates.accountNumber ?? entity.account_number ?? entity.accountNumber) ?? selected.account_number ?? ""
                      );
                      setDailyRate(
                        textValue(updates.daily_rate ?? updates.dailyRate ?? entity.daily_rate ?? entity.dailyRate) ?? selected.daily_rate ?? ""
                      );
                      setNotes(
                        textValue(updates.notes ?? entity.notes) ?? selected.notes ?? ""
                      );
                    }
                  }
                }}
              >
                <option value="">انتخاب کنید...</option>
                {personOptions.map((worker) => (
                  <option key={worker.id} value={worker.id}>
                    {workerLabel(worker)}
                  </option>
                ))}
                {showCreateNew && (
                  <option value={CREATE_NEW_SENTINEL}>
                    {createNewLabel(extractedName, extractedRole)}
                  </option>
                )}
              </select>
            </label>
            <label>
              نام
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              نقش
              {isRoleReadOnly ? (
                <input value={roleLabelFromType(role)} readOnly />
              ) : (
                <select value={role} onChange={(e) => setRole(e.target.value)}>
                  {ROLE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              )}
            </label>
            {showRoleDetail && (
              <label>
                تخصص / توضیح نقش
                <input value={roleDetail} onChange={(e) => setRoleDetail(e.target.value)} />
              </label>
            )}
            {showPhone && (
              <label>
                شماره موبایل
                <input value={phone} onChange={(e) => setPhone(e.target.value)} />
              </label>
            )}
            {showAccount && (
              <label>
                شماره حساب
                <input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} />
              </label>
            )}
            {showDailyRate && (
              <label>
                دستمزد روزانه
                <input value={dailyRate} onChange={(e) => setDailyRate(e.target.value)} />
              </label>
            )}
            {showNotes && (
              <label>
                توضیحات
                <input value={notes} onChange={(e) => setNotes(e.target.value)} />
              </label>
            )}
            <label>
              پروژه
              <input value={projectName || (activeProjectId ? `پروژه ${activeProjectId}` : "ثبت نشده")} readOnly />
            </label>
          </div>
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
