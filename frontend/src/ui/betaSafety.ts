import type { PendingInterpretation } from "../api";

export const UNCERTAIN_INTERPRETATION_MESSAGE = "یارا از این برداشت مطمئن نیست. لطفاً قبل از ثبت بررسی کنید.";
export const MULTI_ACTION_WARNING = "این متن ممکن است شامل چند عملیات باشد. برای دقت بیشتر، هر عملیات را جداگانه وارد کنید.";
export const MONEY_UNIT_HELPER = "مبالغ به تومان ثبت می‌شوند.";

export function moneyWithUnit(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "ثبت نشده";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) {
    const text = String(value).trim();
    return text.includes("تومان") ? text : `${text} تومان`;
  }
  return `${new Intl.NumberFormat("fa-IR").format(numeric)} تومان`;
}

export function looksLikeMultiAction(text: string | null | undefined): boolean {
  const normalized = (text ?? "").trim();
  if (!normalized) return false;

  const actionHints = [
    /گرفتم|گرفت|دریافت|واریز/,
    /دادم|داد|پرداخت|خرج/,
    /کار کرد|کارکرد|دستمزد|حقوق/,
    /شماره تماس|تلفن|موبایل/,
    /شماره حساب|حساب|کارت|شبا/,
  ];
  const hintCount = actionHints.filter((pattern) => pattern.test(normalized)).length;
  const hasConnector = /\sو\s|،|؛/.test(normalized);

  return hasConnector && hintCount >= 2;
}

export function interpretationText(interpretation: PendingInterpretation): string {
  return interpretation.matched_input_text || interpretation.description || interpretation.raw_input_text || "";
}

export function isUncertainInterpretation(interpretation: PendingInterpretation): boolean {
  const confidence = interpretation.confidence;
  const domain = String(interpretation.domain_route?.domain ?? "");
  const hasUnknownDomain = !domain || domain === "OTHER" || domain === "UNKNOWN";
  const hasMissingFinancialFields = interpretation.canonical_event_type === "FINANCIAL_EVENT"
    && (!interpretation.extracted_amount || !interpretation.financial_direction);

  return Boolean(
    (confidence !== null && confidence < 0.5)
    || interpretation.semantic_action === "NOTE"
    || hasUnknownDomain
    || hasMissingFinancialFields
  );
}
