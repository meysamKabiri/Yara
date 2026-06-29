import { useState } from "react";
import type { PendingInterpretation, Worker } from "../../api";
import { ROLE_OPTIONS, FINANCIAL_DIRECTION_OPTIONS, PAYMENT_METHOD_OPTIONS } from "../../constants";
import {
  MONEY_UNIT_HELPER,
  MULTI_ACTION_WARNING,
  UNCERTAIN_INTERPRETATION_MESSAGE,
  interpretationText,
  isUncertainInterpretation,
  looksLikeMultiAction,
  moneyWithUnit,
} from "../betaSafety";

interface SplitFlowConfirmData {
  setup: {
    name: string;
    type: string;
    roleDetail: string | null;
    phone: string | null;
    accountNumber: string | null;
  };
  financial: {
    entity_id: number;
    amount: string;
    direction: string;
    payment_method: string;
  };
}

interface SplitFlowModalProps {
  interpretation: PendingInterpretation;
  workers: Worker[];
  activeProjectId: number | null;
  isLoading: boolean;
  onConfirm: (data: SplitFlowConfirmData) => void;
  onDiscard: () => void;
}

function shouldShowRoleDetail(type: string): boolean {
  return type === "SKILLED_WORKER" || type === "OTHER";
}

function directionImpactText(direction: string, amount: string): string {
  const formattedAmount = moneyWithUnit(amount);
  if (direction === "INCOMING") return `بعد از تأیید، مبلغ ${formattedAmount} به عنوان دریافتی پروژه ثبت می‌شود و موجودی نقدی پروژه افزایش پیدا می‌کند.`;
  if (direction === "OUTGOING" || direction === "DEBT" || direction === "DEFERRED") return `بعد از تأیید، مبلغ ${formattedAmount} به عنوان پرداختی پروژه ثبت می‌شود و موجودی نقدی پروژه کاهش پیدا می‌کند.`;
  return "اثر مالی این ثبت بعد از تأیید مشخص می‌شود؛ جهت مالی را بررسی کنید.";
}

export function SplitFlowModal({
  interpretation,
  workers,
  activeProjectId,
  isLoading,
  onConfirm,
  onDiscard,
}: SplitFlowModalProps) {
  const [step, setStep] = useState<1 | 2>(1);

  const entity = (interpretation.extracted_entities ?? [])[0] ?? {};
  const initialName = typeof entity.name === "string" ? entity.name : "";
  const projectRole = typeof entity.project_role === "string" ? entity.project_role
    : typeof entity.type === "string" ? entity.type : "OTHER";

  const [setupName, setSetupName] = useState(initialName);
  const [setupType, setSetupType] = useState(projectRole);
  const [setupRoleDetail, setSetupRoleDetail] = useState(
    typeof entity.role_detail === "string" ? entity.role_detail : "",
  );
  const [setupPhone, setSetupPhone] = useState(
    typeof entity.phone === "string" ? entity.phone : "",
  );
  const [setupAccountNumber, setSetupAccountNumber] = useState(
    typeof entity.account_number === "string" ? entity.account_number : "",
  );

  const [financialEntityId, setFinancialEntityId] = useState<number | null>(
    interpretation.suggested_entity_id ?? null,
  );
  const [amount, setAmount] = useState(interpretation.extracted_amount ?? "");
  const [direction, setDirection] = useState(interpretation.financial_direction ?? "");
  const [paymentMethod, setPaymentMethod] = useState(interpretation.payment_method ?? "");
  const multiActionWarning = looksLikeMultiAction(interpretationText(interpretation));
  const uncertaintyWarning = isUncertainInterpretation(interpretation);

  function handleFinalConfirm() {
    if (!financialEntityId) return;
    onConfirm({
      setup: {
        name: setupName.trim(),
        type: setupType,
        roleDetail: shouldShowRoleDetail(setupType) ? setupRoleDetail.trim() || null : null,
        phone: setupPhone.trim() || null,
        accountNumber: setupAccountNumber.trim() || null,
      },
      financial: {
        entity_id: financialEntityId,
        amount: amount.trim(),
        direction,
        payment_method: paymentMethod,
      },
    });
  }

  const step1Valid = setupName.trim().length > 0;
  const step2Valid = Boolean(financialEntityId && amount.trim());

  const entityOptions = workers.filter((w) =>
    w.type === "CLIENT" || w.type === "VENDOR",
  );

  if (step === 1) {
    return (
      <article className="interpretation-card modal-shell">
        <header className="modal-header">
          <div>
            <h3 className="modal-title">اطلاعات فرد</h3>
            <p>مرحله ۱ از ۲</p>
          </div>
        </header>
        <section className="approval-section modal-body">
          {uncertaintyWarning && <p className="warning-text">{UNCERTAIN_INTERPRETATION_MESSAGE}</p>}
          {multiActionWarning && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
          <div className="setup-edit-list">
            <div className="setup-edit-row">
              <label>
                نام
                <input value={setupName} onChange={(e) => setSetupName(e.target.value)} />
              </label>
              <label>
                نقش
                <select value={setupType} onChange={(e) => setSetupType(e.target.value)}>
                  {ROLE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </label>
              {shouldShowRoleDetail(setupType) && (
                <label>
                  تخصص / توضیح نقش
                  <input value={setupRoleDetail} onChange={(e) => setSetupRoleDetail(e.target.value)} />
                </label>
              )}
              <label>
                شماره موبایل
                <input value={setupPhone} onChange={(e) => setSetupPhone(e.target.value)} />
              </label>
              <label>
                شماره حساب
                <input value={setupAccountNumber} onChange={(e) => setSetupAccountNumber(e.target.value)} />
              </label>
              <label>
                پروژه
                <input value={activeProjectId ? `پروژه ${activeProjectId}` : "ثبت نشده"} readOnly />
              </label>
            </div>
          </div>
        </section>
        <div className="modal-footer">
          <div className="modal-actions">
            <button
              className="primary-action"
              type="button"
              onClick={() => setStep(2)}
              disabled={isLoading || !step1Valid}
            >
              مرحله بعد
            </button>
            <button className="danger-action" type="button" onClick={onDiscard} disabled={isLoading}>
              حذف
            </button>
          </div>
        </div>
      </article>
    );
  }

  return (
    <article className="interpretation-card modal-shell">
      <header className="modal-header">
        <div>
          <h3 className="modal-title">ثبت مالی</h3>
          <p>مرحله ۲ از ۲</p>
          <p>{MONEY_UNIT_HELPER}</p>
        </div>
      </header>
      <section className="approval-section modal-body">
        {uncertaintyWarning && <p className="warning-text">{UNCERTAIN_INTERPRETATION_MESSAGE}</p>}
        {multiActionWarning && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
        <div className="confirmation-summary">
          <p><strong>مبلغ:</strong> {moneyWithUnit(amount)}</p>
          <p><strong>اثر بعد از تأیید:</strong> <span className="impact-text">{directionImpactText(direction, amount)}</span></p>
        </div>
        <div className="edit-grid">
          <label>
            طرف حساب
            <select
              value={financialEntityId ?? ""}
              onChange={(e) => setFinancialEntityId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">انتخاب کنید...</option>
              {entityOptions.map((w) => (
                <option key={w.id} value={w.id}>{w.name}</option>
              ))}
            </select>
          </label>
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
            پروژه
            <input value={activeProjectId ? `پروژه ${activeProjectId}` : "ثبت نشده"} readOnly />
        </label>
      </div>
    </section>
      <div className="modal-footer">
        <div className="modal-actions">
          <button
            className="primary-action"
            type="button"
            onClick={handleFinalConfirm}
            disabled={isLoading || !step2Valid}
          >
            تایید نهایی
          </button>
          <button type="button" onClick={() => setStep(1)} disabled={isLoading}>
            مرحله قبل
          </button>
          <button className="danger-action" type="button" onClick={onDiscard} disabled={isLoading}>
            حذف
          </button>
        </div>
      </div>
    </article>
  );
}
