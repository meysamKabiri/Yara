import { useState } from "react";
import type { PendingInterpretation, Worker } from "../../api";
import { ROLE_OPTIONS } from "../../constants";
import type { SetupEntity } from "../../types/domain";

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
    <article className="interpretation-card">
      <section className="approval-section">
        <span className="eyebrow">افزودن فرد به پروژه</span>
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
      <div className="modal-actions">
        <button
          className="primary-action"
          type="button"
          onClick={handleConfirm}
          disabled={isLoading || !canConfirm}
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
