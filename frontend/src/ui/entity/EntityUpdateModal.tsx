import { useState } from "react";
import type { PendingInterpretation, Worker } from "../../api";
import { ROLE_OPTIONS } from "../../constants";

interface EntityUpdateModalProps {
  interpretation: PendingInterpretation;
  workers: Worker[];
  activeProjectId: number | null;
  isLoading: boolean;
  onConfirm: (data: {
    name: string;
    phone: string | null;
    accountNumber: string | null;
    role: string;
    roleDetail: string | null;
  }) => void;
  onDiscard: () => void;
}

function shouldShowRoleDetail(type: string): boolean {
  return type === "SKILLED_WORKER" || type === "OTHER";
}

export function EntityUpdateModal({
  interpretation,
  activeProjectId,
  isLoading,
  onConfirm,
  onDiscard,
}: EntityUpdateModalProps) {
  const entity = (interpretation.extracted_entities ?? [])[0] ?? {};
  const updates = typeof entity.field_updates === "object" && entity.field_updates !== null
    ? entity.field_updates as Record<string, unknown>
    : {};

  function textValue(value: unknown): string | null {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number") return String(value);
    return null;
  }

  const initialName = typeof entity.name === "string" ? entity.name : "";
  const initialRole = textValue(updates.project_role ?? updates.type) ?? textValue(entity.project_role ?? entity.type) ?? "OTHER";
  const initialRoleDetail = textValue(updates.role_detail ?? entity.role_detail) ?? "";
  const initialPhone = textValue(updates.phone ?? entity.phone) ?? "";
  const initialAccountNumber = textValue(updates.account_number ?? entity.account_number) ?? "";

  const [name, setName] = useState(initialName);
  const [role, setRole] = useState(initialRole);
  const [roleDetail, setRoleDetail] = useState(initialRoleDetail);
  const [phone, setPhone] = useState(initialPhone);
  const [accountNumber, setAccountNumber] = useState(initialAccountNumber);

  function handleConfirm() {
    onConfirm({
      name: name.trim(),
      phone: phone.trim() || null,
      accountNumber: accountNumber.trim() || null,
      role,
      roleDetail: shouldShowRoleDetail(role) ? roleDetail.trim() || null : null,
    });
  }

  return (
    <article className="interpretation-card">
      <section className="approval-section">
        <span className="eyebrow">به‌روزرسانی اطلاعات فرد</span>
        <div className="setup-edit-list">
          <div className="setup-edit-row">
            <label>
              نام
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              نقش
              <select value={role} onChange={(e) => setRole(e.target.value)}>
                {ROLE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </label>
            {shouldShowRoleDetail(role) && (
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
          </div>
        </div>
      </section>
      <div className="modal-actions">
        <button
          className="primary-action"
          type="button"
          onClick={handleConfirm}
          disabled={isLoading || !name.trim()}
        >
          تایید
        </button>
        <button className="danger-action" type="button" onClick={onDiscard} disabled={isLoading}>
          حذف
        </button>
      </div>
    </article>
  );
}
