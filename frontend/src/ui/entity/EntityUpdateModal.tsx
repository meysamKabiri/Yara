import { useEffect, useState } from "react";
import type { PendingInterpretation, Worker } from "../../api";
import { api } from "../../api";
import { ROLE_OPTIONS, roleLabel } from "../../constants";
import { buildConfirmPayload, exactEntityIdByName, getCandidateEntityId, normalizeNeedsSelection, type NeedsSelectionCandidate } from "../confirmPayload";
import {
  MULTI_ACTION_WARNING,
  UNCERTAIN_INTERPRETATION_MESSAGE,
  interpretationText,
  isUncertainInterpretation,
  looksLikeMultiAction,
  moneyWithUnit,
} from "../betaSafety";

const CREATE_NEW_SENTINEL = -1;

function firstEntity(interpretation: PendingInterpretation): Record<string, unknown> {
  return interpretation.extracted_entities?.[0] ?? {};
}

function roleLabelFromType(type: string | undefined): string {
  return type ? roleLabel(type) : "فرد";
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

function variantLabel(variant: EntityUpdateVariant): string {
  if (variant === "PHONE_UPDATE") return "ثبت شماره تماس";
  if (variant === "ACCOUNT_UPDATE") return "ثبت شماره حساب";
  if (variant === "DAILY_RATE_UPDATE") return "ثبت دستمزد روزانه";
  if (variant === "NOTES_UPDATE") return "ثبت توضیحات پروفایل";
  return "به‌روزرسانی اطلاعات فرد";
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
    _skipApiConfirm?: boolean;
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
  const extractedName = textValue(entity.name) ?? "";
  const extractedRole = textValue(entity.project_role ?? entity.type) ?? "DAILY_WORKER";

  const nameMatchWorkerId = exactEntityIdByName(extractedName, workers);
  const nameMatchWorker = nameMatchWorkerId
    ? workers.find((worker) => worker.id === nameMatchWorkerId) ?? null
    : null;

  const initialEntityId = interpretation.suggested_entity_id
    ?? candidates[0]?.id
    ?? nameMatchWorker?.id
    ?? null;

  const hasExisting = initialEntityId !== null;
  const showCreateNew = !hasExisting && extractedName.length > 0;

  // Selection mode state (NEEDS_SELECTION handler)
  const [selectionCandidates, setSelectionCandidates] = useState<NeedsSelectionCandidate[] | null>(null);
  const [localLoading, setLocalLoading] = useState(false);
  const isLoadingActive = isLoading || localLoading;

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

  useEffect(() => {
    if (initialEntityId && entityId !== initialEntityId) {
      setEntityId(initialEntityId);
    }
  }, [entityId, initialEntityId]);

  const showPhone = variant === "PHONE_UPDATE" || (variant === "GENERAL_PROFILE_UPDATE" && hasPhoneUpdate);
  const showAccount = variant === "ACCOUNT_UPDATE" || (variant === "GENERAL_PROFILE_UPDATE" && hasAccountUpdate);
  const showDailyRate = variant === "DAILY_RATE_UPDATE" || (variant === "GENERAL_PROFILE_UPDATE" && hasDailyRateUpdate);
  const showNotes = variant === "NOTES_UPDATE";
  const showRoleDetail = variant === "GENERAL_PROFILE_UPDATE" && hasRoleDetailUpdate;
  const isRoleReadOnly = variant !== "GENERAL_PROFILE_UPDATE" && !isCreatingNew;

  const isFieldUpdate = hasPhoneUpdate || hasAccountUpdate || hasDailyRateUpdate || hasNotesUpdate;
  const multiActionWarning = looksLikeMultiAction(interpretationText(interpretation));
  const uncertaintyWarning = isUncertainInterpretation(interpretation);

  function buildFieldUpdatesFromForm(): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    if (showPhone && phone.trim()) result.phone = phone.trim();
    if (showAccount && accountNumber.trim()) result.account_number = accountNumber.trim();
    if (showDailyRate && dailyRate.trim()) result.daily_rate = dailyRate.trim();
    if (roleDetail.trim()) result.role_detail = roleDetail.trim();
    return result;
  }

  function buildConfirmData(entityIdParam?: number | null, overrideName?: string, overrideRole?: string) {
    return {
      entityId: entityIdParam ?? null,
      name: (overrideName || name).trim(),
      phone: showPhone ? (phone.trim() || null) : null,
      accountNumber: showAccount ? (accountNumber.trim() || null) : null,
      dailyRate: showDailyRate ? (dailyRate.trim() || null) : null,
      role: overrideRole || role,
      roleDetail: showRoleDetail ? (shouldShowRoleDetail(overrideRole || role) ? roleDetail.trim() || null : null) : null,
    };
  }

  /** Try to confirm directly, or let the backend return NEEDS_SELECTION for explicit selection.
   *  Returns candidates if NEEDS_SELECTION, true if confirm succeeded, null on other errors. */
  async function tryNeedsSelection(): Promise<NeedsSelectionCandidate[] | "confirmed" | null> {
    const updates = buildFieldUpdatesFromForm();
    await api.updatePendingInterpretation(interpretation.id, {
      extracted_entities: [
        {
          ...firstEntity(interpretation),
          name: name.trim(),
          field_updates: updates,
        },
      ],
    });
    try {
      await api.confirmPendingInterpretation(interpretation.id, buildConfirmPayload(initialEntityId));
      return "confirmed";
    } catch (err: unknown) {
      const candidates = normalizeNeedsSelection(err);
      if (candidates) return candidates;
      return null;
    }
  }

  async function handleConfirm() {
    const effectiveEntityId = entityId && !isCreatingNew ? entityId : null;
    const matchId = effectiveEntityId ?? (nameMatchWorker?.id ?? null);

    if (matchId) {
      onConfirm(buildConfirmData(matchId));
      return;
    }

    if (!isFieldUpdate) {
      // SET_ROLE or non-field-update: safe to create new
      const updates = buildFieldUpdatesFromForm();
      onConfirm({
        ...buildConfirmData(null),
        create_new_entity: true,
        entity_name: name.trim(),
        project_role: role,
        field_updates: Object.keys(updates).length > 0 ? updates : undefined,
      });
      return;
    }

    // Entity update (phone/account etc.) with no known entity → try NEEDS_SELECTION
    setLocalLoading(true);
    try {
      const result = await tryNeedsSelection();
      if (result === "confirmed") {
        // Modal already confirmed via NEEDS_SELECTION path; parent should skip API call
        onConfirm({ ...buildConfirmData(null), _skipApiConfirm: true });
        return;
      }
      if (result && result.length > 0) {
        setSelectionCandidates(result);
        return;
      }
      // No candidates found — safe to create new
      const updates = buildFieldUpdatesFromForm();
      onConfirm({
        ...buildConfirmData(null),
        create_new_entity: true,
        entity_name: name.trim(),
        project_role: role,
        field_updates: Object.keys(updates).length > 0 ? updates : undefined,
      });
    } catch {
    } finally {
      setLocalLoading(false);
    }
  }

  function handleSelectCandidate(candidateId: number) {
    const candidate = selectionCandidates?.find((c) => getCandidateEntityId(c) === candidateId);
    setSelectionCandidates(null);
    onConfirm(buildConfirmData(getCandidateEntityId(candidate ?? {}) ?? candidateId, candidate?.name, candidate?.type));
  }

  function handleCreateNewFromSelection() {
    setSelectionCandidates(null);
    const updates = buildFieldUpdatesFromForm();
    onConfirm({
      ...buildConfirmData(null),
      create_new_entity: true,
      entity_name: name.trim(),
      project_role: role,
      field_updates: Object.keys(updates).length > 0 ? updates : undefined,
    });
  }

  const canConfirm = isCreatingNew
    ? Boolean(name.trim() && role)
    : Boolean(entityId && name.trim());

  return (
    <article className="interpretation-card modal-shell">
      {selectionCandidates ? (
        <>
          <header className="modal-header">
            <div>
              <h3 className="modal-title">انتخاب فرد</h3>
              <p>فرد مرتبط را انتخاب کنید.</p>
            </div>
          </header>
          <section className="approval-section modal-body">
            <div className="candidate-list">
              {selectionCandidates.map((candidate, index) => (
                <button
                  key={getCandidateEntityId(candidate) ?? candidate.name ?? index}
                  className="candidate-button primary-action"
                  type="button"
                  onClick={() => {
                    const candidateId = getCandidateEntityId(candidate);
                    if (candidateId !== null) handleSelectCandidate(candidateId);
                  }}
                  disabled={localLoading}
                >
                  {candidate.name} - {roleLabelFromType(candidate.type)}
                </button>
              ))}
              <button
                className="candidate-button"
                type="button"
                onClick={handleCreateNewFromSelection}
                disabled={localLoading}
              >
                شخص جدید بساز
              </button>
            </div>
          </section>
          <div className="modal-footer">
            <div className="modal-actions">
              <button className="danger-action" type="button" onClick={onDiscard} disabled={localLoading}>
                انصراف
              </button>
            </div>
          </div>
        </>
      ) : (
        <>
          <header className="modal-header">
            <div>
              <h3 className="modal-title">به‌روزرسانی اطلاعات فرد</h3>
              <p>برداشت سیستم از متن شما: تغییرات فرد را بررسی کنید.</p>
            </div>
          </header>
          <section className="approval-section modal-body">
            {uncertaintyWarning && <p className="warning-text">{UNCERTAIN_INTERPRETATION_MESSAGE}</p>}
            {multiActionWarning && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
            <div className="confirmation-summary">
              <p><strong>نوع عملیات:</strong> {variantLabel(variant)}</p>
              <p><strong>شخص / طرف حساب:</strong> {name || extractedName || "نامشخص"}</p>
              {showPhone && <p><strong>شماره تماس:</strong> {phone || "ثبت نشده"}</p>}
              {showAccount && <p><strong>شماره حساب:</strong> {accountNumber || "ثبت نشده"}</p>}
              {showDailyRate && <p><strong>مبلغ:</strong> {moneyWithUnit(dailyRate)}</p>}
              <p><strong>اثر بعد از تأیید:</strong> <span className="impact-text">این ثبت موجودی مالی پروژه را تغییر نمی‌دهد.</span></p>
              <p>قبل از تأیید می‌توانید فرد، نام و فیلدهای نمایش‌داده‌شده را اصلاح کنید.</p>
            </div>
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
                    <small>مبالغ به تومان ثبت می‌شوند.</small>
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
          <div className="modal-footer">
            <div className="modal-actions">
              <button
                className="primary-action"
                type="button"
                onClick={handleConfirm}
                disabled={isLoadingActive || !canConfirm}
              >
                تأیید و ثبت
              </button>
              <button className="danger-action" type="button" onClick={onDiscard} disabled={isLoadingActive}>
                رد کردن
              </button>
            </div>
          </div>
        </>
      )}
    </article>
  );
}
