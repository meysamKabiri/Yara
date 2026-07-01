import type { FinancialDirection, PaymentType, RoleRegistryResponse, WorkerType } from "./api";

export const ROLE_OPTIONS: Array<{ value: WorkerType; label: string }> = [
  { value: "CLIENT", label: "کارفرما" },
  { value: "DAILY_WORKER", label: "کارگر" },
  { value: "VENDOR", label: "فروشنده" },
  { value: "SKILLED_WORKER", label: "استادکار" },
  { value: "OTHER", label: "سایر" },
];

export function applyRoleRegistry(registry: RoleRegistryResponse): void {
  if (!registry.frontend_options.length) return;
  ROLE_OPTIONS.splice(0, ROLE_OPTIONS.length, ...registry.frontend_options);
}

export function roleLabel(value: WorkerType | string | null | undefined): string {
  return ROLE_OPTIONS.find((option) => option.value === value)?.label ?? "سایر";
}

export const PAYMENT_METHOD_OPTIONS: Array<{ value: PaymentType | ""; label: string }> = [
  { value: "", label: "انتخاب نشده" },
  { value: "CASH", label: "نقدی" },
  { value: "BANK_TRANSFER", label: "کارت/انتقال بانکی" },
  { value: "CHECK", label: "چک" },
  { value: "OTHER", label: "سایر" },
];

export const FINANCIAL_DIRECTION_OPTIONS: Array<{ value: FinancialDirection | ""; label: string }> = [
  { value: "", label: "انتخاب نشده" },
  { value: "INCOMING", label: "ورودی به پروژه" },
  { value: "OUTGOING", label: "خروجی از پروژه" },
  { value: "DEBT", label: "بدهی / پرداخت‌نشده" },
  { value: "DEFERRED", label: "مدت‌دار / چک" },
];

export const SEMANTIC_ACTION_OPTIONS = [
  { value: "PAYMENT", label: "دریافتی/پرداخت" },
  { value: "PURCHASE_PAID", label: "خرید پرداخت‌شده" },
  { value: "DEBT_CREATED", label: "خرید نسیه / بدهی" },
  { value: "CHECK_PAYMENT", label: "پرداخت چک" },
  { value: "INCREMENT", label: "ثبت کارکرد" },
];
