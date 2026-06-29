import { useState } from "react";
import type { PendingInterpretation, Worker } from "../../api";
import { ROLE_OPTIONS } from "../../constants";
import type { SetupEntity } from "../../types/domain";
import {
  MULTI_ACTION_WARNING,
  UNCERTAIN_INTERPRETATION_MESSAGE,
  interpretationText,
  isUncertainInterpretation,
  looksLikeMultiAction,
} from "../betaSafety";

interface SetupModalProps {
  interpretation: PendingInterpretation;
  workers: Worker[];
  activeProjectId: number | null;
  projectName?: string | null;
  isLoading: boolean;
  onConfirm: (entities: SetupEntity[]) => void;
  onDiscard: () => void;
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

function shouldShowRoleDetail(type: string): boolean {
  return type === "SKILLED_WORKER" || type === "OTHER";
}

function roleLabel(type: string): string {
  return ROLE_OPTIONS.find((option) => option.value === type)?.label ?? type;
}

function extractSetupEntities(interpretation: PendingInterpretation): SetupEntity[] {
  return (interpretation.extracted_entities ?? [])
    .map((entity) => {
      const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
        ? entity.field_updates as Record<string, unknown>
        : {};
      return {
        name: typeof entity.name === "string" ? entity.name : "",
        type: entityTypeFromRecord(entity),
        roleDetail: typeof (updates.role_detail ?? entity.role_detail) === "string"
          ? (updates.role_detail ?? entity.role_detail) as string
          : null,
        phone: typeof (updates.phone ?? entity.phone) === "string"
          ? (updates.phone ?? entity.phone) as string
          : null,
        accountNumber: typeof (updates.account_number ?? entity.account_number) === "string"
          ? (updates.account_number ?? entity.account_number) as string
          : null,
      };
    })
    .filter((entity) => entity.name.trim());
}

export function SetupModal({
  interpretation,
  activeProjectId,
  projectName,
  isLoading,
  onConfirm,
  onDiscard,
}: SetupModalProps) {
  const initial = extractSetupEntities(interpretation);
  const defaultEntity: SetupEntity = initial.length > 0
    ? initial[0]
    : { name: "", type: "OTHER", roleDetail: null, phone: null, accountNumber: null };

  const [name, setName] = useState(defaultEntity.name);
  const [type, setType] = useState(defaultEntity.type);
  const [roleDetail, setRoleDetail] = useState(defaultEntity.roleDetail ?? "");
  const [phone, setPhone] = useState(defaultEntity.phone ?? "");
  const [accountNumber, setAccountNumber] = useState(defaultEntity.accountNumber ?? "");
  const multiActionWarning = looksLikeMultiAction(interpretationText(interpretation));
  const uncertaintyWarning = isUncertainInterpretation(interpretation);

  function handleConfirm() {
    const entity: SetupEntity = {
      name: name.trim(),
      type,
      roleDetail: shouldShowRoleDetail(type) ? roleDetail.trim() || null : null,
      phone: phone.trim() || null,
      accountNumber: accountNumber.trim() || null,
    };
    onConfirm([entity]);
  }

  const canConfirm = name.trim().length > 0;

  return (
    <article className="interpretation-card modal-shell">
      <header className="modal-header">
        <div>
          <h3 className="modal-title">افزودن فرد به پروژه</h3>
          <p>برداشت سیستم از متن شما: اطلاعات فرد و نقش را بررسی کنید.</p>
        </div>
      </header>
      <section className="approval-section modal-body">
        {uncertaintyWarning && <p className="warning-text">{UNCERTAIN_INTERPRETATION_MESSAGE}</p>}
        {multiActionWarning && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
        <div className="confirmation-summary">
          <p><strong>نوع عملیات:</strong> تعریف / به‌روزرسانی فرد در پروژه</p>
          <p><strong>شخص / طرف حساب:</strong> {name || "نامشخص"}</p>
          <p><strong>نقش / دسته:</strong> {roleLabel(type)}</p>
          {roleDetail.trim() && <p><strong>توضیح نقش:</strong> {roleDetail}</p>}
          <p><strong>اثر بعد از تأیید:</strong> <span className="impact-text">این ثبت موجودی مالی پروژه را تغییر نمی‌دهد.</span></p>
          <p>قبل از تأیید می‌توانید نام، نقش، شماره تماس و شماره حساب را اصلاح کنید.</p>
        </div>
        <div className="setup-edit-list">
          <div className="setup-edit-row">
            <label>
              نام
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              نقش
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {ROLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </label>
            {shouldShowRoleDetail(type) && (
              <label>
                تخصص / توضیح نقش
                <input value={roleDetail} onChange={(e) => setRoleDetail(e.target.value)} />
              </label>
            )}
            <label>
              شماره موبایل
              <input value={phone} onChange={(e) => setPhone(e.target.value)} />
            </label>
            <label>
              شماره حساب
              <input value={accountNumber} onChange={(e) => setAccountNumber(e.target.value)} />
            </label>
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
            disabled={isLoading || !canConfirm}
          >
            تأیید و ثبت
          </button>
          <button className="danger-action" type="button" onClick={onDiscard} disabled={isLoading}>
            رد کردن
          </button>
        </div>
      </div>
    </article>
  );
}
