import { useState } from "react";
import type { FinancialDirection, PaymentType, PendingInterpretation, Worker } from "../../api";
import { FINANCIAL_DIRECTION_OPTIONS, PAYMENT_METHOD_OPTIONS } from "../../constants";

interface FinancialModalProps {
  interpretation: PendingInterpretation;
  workers: Worker[];
  activeProjectId: number | null;
  isLoading: boolean;
  onConfirm: (data: {
    entity_id: number;
    amount: string;
    direction: string;
    payment_method: string;
  }) => void;
  onDiscard: () => void;
}

export function FinancialModal({
  interpretation,
  workers,
  activeProjectId,
  isLoading,
  onConfirm,
  onDiscard,
}: FinancialModalProps) {
  const resolvedEntityId = interpretation.suggested_entity_id ?? null;
  const resolvedWorker = resolvedEntityId
    ? workers.find((w) => w.id === resolvedEntityId)
    : undefined;

  const [entityId, setEntityId] = useState<number | null>(resolvedEntityId);
  const [amount, setAmount] = useState(interpretation.extracted_amount ?? "");
  const [direction, setDirection] = useState(interpretation.financial_direction ?? "");
  const [paymentMethod, setPaymentMethod] = useState(interpretation.payment_method ?? "");

  function handleConfirm() {
    if (!entityId) return;
    onConfirm({
      entity_id: entityId,
      amount: amount.trim(),
      direction,
      payment_method: paymentMethod,
    });
  }

  const canConfirm = Boolean(entityId && amount.trim());

  const entityOptions = workers.filter((w) =>
    w.type === "CLIENT" || w.type === "VENDOR"
  );

  return (
    <article className="interpretation-card">
      <section className="approval-section">
        <span className="eyebrow">برداشت مالی</span>
        <div className="edit-grid">
          <label>
            طرف حساب
            <select
              value={entityId ?? ""}
              onChange={(e) => setEntityId(e.target.value ? Number(e.target.value) : null)}
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
