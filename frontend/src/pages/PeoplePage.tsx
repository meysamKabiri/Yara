import {
  Building2,
  ChevronRight,
  Clock,
  CreditCard,
  Hammer,
  Phone,
  ReceiptText,
  UserRound,
  Users,
  Wallet,
} from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Invoice, OperatingSummary, Payment, Project, Worker, WorkerState, WorkLog, WorkerType } from "../api";
import { ROLE_OPTIONS, roleLabel } from "../constants";

type PeoplePageProps = {
  projects: Project[];
  selectedProjectId: number | null;
  onProjectChange: (projectId: number) => void;
  workers: Worker[];
  workerStates: WorkerState[];
  payments: Payment[];
  workLogs: WorkLog[];
  invoices: Invoice[];
  summary: OperatingSummary | null;
  selectedPersonId: number | null;
  onOpenPerson: (personId: number) => void;
  onBackToPeople: () => void;
  onUpdateWorker: (workerId: number, payload: Partial<Pick<Worker, "name" | "type" | "role_detail" | "phone" | "account_number" | "daily_rate" | "notes">>) => Promise<void>;
};

type PersonKind = Worker["type"] | "OTHER";

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function personKind(worker: Worker): PersonKind {
  if (["CLIENT", "DAILY_WORKER", "SKILLED_WORKER", "VENDOR"].includes(worker.type)) {
    return worker.type;
  }
  return "OTHER";
}

function specialty(worker: Worker): string {
  return worker.role_detail || "تخصص ثبت نشده";
}

function personDisplayRole(worker: Worker): string {
  const kind = personKind(worker);
  if ((kind === "SKILLED_WORKER" || kind === "OTHER") && worker.role_detail?.trim()) {
    return worker.role_detail.trim();
  }
  return roleLabel(kind);
}

function paymentTotal(payments: Payment[], directions: Payment["direction"][]): number {
  return payments
    .filter((payment) => directions.includes(payment.direction))
    .reduce((total, payment) => total + Number(payment.amount || 0), 0);
}

const PAYMENT_DIRECTION_LABELS: Record<Payment["direction"], string> = {
  INCOMING: "دریافتی",
  OUTGOING: "پرداخت واقعی",
  DEBT: "بدهی",
  DEFERRED: "پرداخت مدت‌دار",
};

const INVOICE_STATUS_LABELS: Record<Invoice["status"], string> = {
  OPEN: "پرداخت‌نشده",
  PARTIAL: "بخشی پرداخت شده",
  PAID: "پرداخت شده",
};

function clientStatus(summary: OperatingSummary | null) {
  const clientReceivable = Number(summary?.client_receivable ?? 0);
  const availableBalance = Number(summary?.available_balance ?? 0);

  if (clientReceivable > 0) {
    return { label: "بدهکار", badgeClassName: "status-negative" };
  }
  if (availableBalance > 0) {
    return { label: "موجودی مثبت", badgeClassName: "status-positive" };
  }
  return { label: "تسویه", badgeClassName: "status-neutral" };
}

function workerStatus(balance: number) {
  if (balance > 0) return { label: "طلبکار", badgeClassName: "status-positive" };
  if (balance < 0) return { label: "بدهکار", badgeClassName: "status-negative" };
  return { label: "تسویه", badgeClassName: "status-neutral" };
}

function vendorStatus(openPayable: number) {
  if (openPayable > 0) return { label: "بدهی باز", badgeClassName: "status-negative" };
  return { label: "بدون بدهی", badgeClassName: "status-positive" };
}

function DetailList({ children }: { children: ReactNode }) {
  return <dl className="detail-list">{children}</dl>;
}

function DetailItem({ label, value }: { label: ReactNode; value: ReactNode }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>;
}

function PaymentList({ payments }: { payments: Payment[] }) {
  return (
    <div className="mini-list">
      {payments.map((payment) => (
        <div className="mini-row" key={payment.id}>
          <strong>{money(payment.amount)}</strong>
          <span>{PAYMENT_DIRECTION_LABELS[payment.direction] ?? "پرداخت"}</span>
        </div>
      ))}
      {payments.length === 0 && <p className="empty-state">پرداختی ثبت نشده است.</p>}
    </div>
  );
}

function InvoiceList({ invoices }: { invoices: Invoice[] }) {
  return (
    <div className="mini-list">
      {invoices.map((invoice) => (
        <div className="mini-row" key={invoice.id}>
          <strong>{money(invoice.total_amount)}</strong>
          <span>{INVOICE_STATUS_LABELS[invoice.status] ?? "فاکتور"}</span>
        </div>
      ))}
      {invoices.length === 0 && <p className="empty-state">فاکتوری ثبت نشده است.</p>}
    </div>
  );
}

export function PeoplePage({
  projects,
  selectedProjectId,
  onProjectChange,
  workers,
  workerStates,
  payments,
  workLogs,
  invoices,
  summary,
  selectedPersonId,
  onOpenPerson,
  onBackToPeople,
  onUpdateWorker,
}: PeoplePageProps) {
  const selected = selectedPersonId ? workers.find((worker) => worker.id === selectedPersonId) : null;
  const [isEditing, setIsEditing] = useState(false);
  const [profileForm, setProfileForm] = useState({
    name: "",
    type: "DAILY_WORKER" as WorkerType,
    role_detail: "",
    phone: "",
    account_number: "",
    daily_rate: "",
    notes: "",
  });

  useEffect(() => {
    if (!selected) return;
    setProfileForm({
      name: selected.name,
      type: selected.type,
      role_detail: selected.role_detail ?? "",
      phone: selected.phone ?? "",
      account_number: selected.account_number ?? "",
      daily_rate: selected.daily_rate ?? "",
      notes: selected.notes ?? "",
    });
    setIsEditing(false);
  }, [selected?.id]);

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    await onUpdateWorker(selected.id, {
      name: profileForm.name,
      type: profileForm.type,
      role_detail: profileForm.role_detail || null,
      phone: profileForm.phone || null,
      account_number: profileForm.account_number || null,
      daily_rate: profileForm.type === "DAILY_WORKER" ? profileForm.daily_rate || null : null,
      notes: profileForm.notes || null,
    });
    setIsEditing(false);
  }

  if (selected) {
    const kind = personKind(selected);
    const state = workerStates.find((item) => item.worker_id === selected.id);
    const personPayments = payments.filter((payment) => payment.entity_id === selected.id);
    const outgoingPayments = personPayments.filter((payment) =>
      payment.direction === "OUTGOING"
    );
    const incomingPayments = personPayments.filter((payment) => payment.direction === "INCOMING");
    const personInvoices = invoices.filter((invoice) => invoice.vendor_id === selected.id);
    const personWorkLogs = workLogs.filter((workLog) => workLog.worker_id === selected.id);
    const paidOut = paymentTotal(personPayments, ["OUTGOING"]);
    const workLogDays = personWorkLogs.reduce((total, workLog) => total + Number(workLog.unit === "day" ? workLog.quantity || 0 : 0), 0);
    const workLogLaborCost = personWorkLogs.reduce((total, workLog) => total + Number(workLog.total_amount || 0), 0);
    const balance = kind === "DAILY_WORKER" ? workLogLaborCost - paidOut : Number(state?.financial_balance ?? 0);
    const invoiceTotal = personInvoices.reduce(
      (total, invoice) => total + Number(invoice.total_amount || 0),
      0,
    );
    const directPurchaseTotal = outgoingPayments
      .filter((payment) => payment.related_invoice_id === null)
      .reduce((total, payment) => total + Number(payment.amount || 0), 0);
    const vendorDebt = Number(
      summary?.vendor_debts.find((debt) => debt.vendor_id === selected.id)?.debt ?? 0,
    );
    const fundingNeed = Number(summary?.total_paid_out ?? 0) + Number(summary?.open_payables ?? 0);
    const receivedFromClient = paymentTotal(incomingPayments, ["INCOMING"]);
    const receivable = Number(summary?.client_receivable ?? 0);
    const available = Number(summary?.available_balance ?? 0);
    const accruedWage = kind === "DAILY_WORKER" ? workLogLaborCost : 0;
    const status = kind === "CLIENT"
      ? clientStatus(summary)
      : kind === "VENDOR"
        ? vendorStatus(vendorDebt)
        : workerStatus(balance);

    return (
      <div className="page-stack">
        <section className="project-topbar">
          <button className="icon-button" type="button" onClick={onBackToPeople} aria-label="بازگشت">
            <ChevronRight aria-hidden="true" size={22} />
          </button>
          <div>
            <span className="eyebrow">جزئیات فرد</span>
            <h1>{selected.name}</h1>
	            <p className="muted">{personDisplayRole(selected)}</p>
          </div>
          <mark className={status.badgeClassName}>وضعیت: {status.label}</mark>
          <button type="button" onClick={() => setIsEditing(!isEditing)}>{isEditing ? "بستن ویرایش" : "ویرایش"}</button>
        </section>

        {isEditing && (
          <form className="panel-card profile-edit-form" onSubmit={saveProfile}>
            <div className="section-title"><div><span className="eyebrow">ویرایش پروفایل</span><h2>اطلاعات فرد</h2></div></div>
            <div className="edit-grid">
              <label>نام<input value={profileForm.name} onChange={(event) => setProfileForm({ ...profileForm, name: event.target.value })} /></label>
              <label>نقش<select value={profileForm.type} onChange={(event) => setProfileForm({ ...profileForm, type: event.target.value as WorkerType })}>{ROLE_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
              {(profileForm.type === "SKILLED_WORKER" || profileForm.type === "OTHER") && <label>تخصص / توضیح نقش<input value={profileForm.role_detail} onChange={(event) => setProfileForm({ ...profileForm, role_detail: event.target.value })} /></label>}
              <label>شماره موبایل<input value={profileForm.phone} onChange={(event) => setProfileForm({ ...profileForm, phone: event.target.value })} /></label>
              <label>شماره حساب<input value={profileForm.account_number} onChange={(event) => setProfileForm({ ...profileForm, account_number: event.target.value })} /></label>
              {profileForm.type === "DAILY_WORKER" && <label>دستمزد روزانه<input inputMode="decimal" value={profileForm.daily_rate} onChange={(event) => setProfileForm({ ...profileForm, daily_rate: event.target.value })} /></label>}
              <label>یادداشت<textarea value={profileForm.notes} onChange={(event) => setProfileForm({ ...profileForm, notes: event.target.value })} /></label>
            </div>
            <div className="modal-actions"><button className="primary-action" type="submit">ذخیره</button></div>
          </form>
        )}

        {kind === "CLIENT" && (
          <>
            <section className="summary-grid">
              <article className="metric-card positive"><Wallet aria-hidden="true" /><span>پرداخت‌شده توسط کارفرما</span><strong>{money(receivedFromClient)}</strong><small>ورودی پروژه</small></article>
              <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>هزینه / نیاز مالی پروژه</span><strong>{money(fundingNeed)}</strong><small>پرداختی‌ها + بدهی باز</small></article>
              <article className={receivable > 0 ? "metric-card negative" : "metric-card"}><CreditCard aria-hidden="true" /><span>طلب پروژه از کارفرما</span><strong>{money(receivable)}</strong><small>{receivable > 0 ? "نیاز به دریافت" : "طلبی ثبت نشده"}</small></article>
              <article className={available > 0 ? "metric-card positive" : "metric-card"}><Wallet aria-hidden="true" /><span>موجودی قابل خرج پروژه</span><strong>{money(available)}</strong><small>مازاد قابل استفاده</small></article>
            </section>
            <section className="content-grid two-column">
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">پروفایل</span><h2>اطلاعات کارفرما</h2></div></div><DetailList><DetailItem label={<><UserRound aria-hidden="true" size={15} />نام</>} value={selected.name} /><DetailItem label="نقش" value="کارفرما" /><DetailItem label={<><Phone aria-hidden="true" size={15} />تلفن</>} value={selected.phone || "ثبت نشده"} /><DetailItem label={<><CreditCard aria-hidden="true" size={15} />شماره حساب</>} value={selected.account_number || "ثبت نشده"} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">مالی</span><h2>وضعیت مالی پروژه</h2></div></div><DetailList><DetailItem label="وضعیت" value={status.label} /><DetailItem label="پرداخت‌شده توسط کارفرما" value={money(receivedFromClient)} /><DetailItem label="هزینه / نیاز مالی پروژه" value={money(fundingNeed)} /><DetailItem label="طلب پروژه از کارفرما" value={money(receivable)} /><DetailItem label="موجودی قابل خرج پروژه" value={money(available)} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">پرداخت</span><h2>پرداخت‌های کارفرما</h2></div></div><PaymentList payments={incomingPayments} /></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">ارتباط</span><h2>پروژه‌های مرتبط</h2></div></div><DetailList><DetailItem label={<><Building2 aria-hidden="true" size={15} />پروژه</>} value="پروژه فعال فعلی" /></DetailList></article>
            </section>
          </>
        )}

        {kind === "DAILY_WORKER" && (
          <>
            <section className="summary-grid">
              <article className="metric-card pending"><Clock aria-hidden="true" /><span>تعداد روز کارکرد</span><strong>{workLogDays.toLocaleString("fa-IR")}</strong><small>حضور روزمزد</small></article>
              <article className="metric-card"><Wallet aria-hidden="true" /><span>دستمزد روزانه</span><strong>{selected.daily_rate ? money(selected.daily_rate) : "دستمزد روزانه ثبت نشده"}</strong><small>{selected.daily_rate ? "مبنای محاسبه" : "دستمزد روزانه ثبت نشده"}</small></article>
              <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>دستمزد محاسبه‌شده</span><strong>{money(accruedWage)}</strong><small>روز × دستمزد</small></article>
              <article className="metric-card negative"><Wallet aria-hidden="true" /><span>مجموع پرداختی</span><strong>{money(paidOut)}</strong><small>{outgoingPayments.length} پرداخت</small></article>
              <article className="metric-card"><CreditCard aria-hidden="true" /><span>مانده طلب کارگر</span><strong>{money(balance)}</strong><small>وضعیت حساب کارگر</small></article>
            </section>
            <section className="content-grid two-column">
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">پروفایل</span><h2>اطلاعات کارگر</h2></div></div><DetailList><DetailItem label="نام" value={selected.name} /><DetailItem label="نقش" value="کارگر ساده / روزمزد" /><DetailItem label="تلفن" value={selected.phone || "ثبت نشده"} /><DetailItem label="شماره حساب" value={selected.account_number || "ثبت نشده"} /><DetailItem label="یادداشت" value={selected.notes || "ثبت نشده"} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">کار</span><h2>کارکرد</h2></div></div><DetailList><DetailItem label="تعداد روز کارکرد" value={workLogDays.toLocaleString("fa-IR")} /><DetailItem label="دستمزد روزانه" value={selected.daily_rate ? money(selected.daily_rate) : "دستمزد روزانه ثبت نشده"} /><DetailItem label="دستمزد محاسبه‌شده" value={money(accruedWage)} /><DetailItem label="مانده طلب کارگر" value={money(balance)} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">پرداخت</span><h2>پرداخت‌ها</h2></div></div><PaymentList payments={outgoingPayments} /></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">ارتباط</span><h2>پروژه‌های مرتبط</h2></div></div><DetailList><DetailItem label="پروژه" value="پروژه فعال فعلی" /></DetailList></article>
            </section>
          </>
        )}

        {kind === "SKILLED_WORKER" && (
          <>
            <section className="summary-grid">
              <article className="metric-card pending"><Hammer aria-hidden="true" /><span>میزان کارکرد</span><strong>{state?.total_quantity ?? "۰"}</strong><small>{state?.unit ?? "واحد ثبت نشده"}</small></article>
              <article className="metric-card"><Hammer aria-hidden="true" /><span>تخصص</span><strong>{specialty(selected)}</strong><small>نقش تخصصی</small></article>
              <article className="metric-card negative"><Wallet aria-hidden="true" /><span>مجموع پرداختی</span><strong>{money(paidOut)}</strong><small>{outgoingPayments.length} پرداخت</small></article>
              <article className="metric-card"><CreditCard aria-hidden="true" /><span>مانده حساب</span><strong>{money(balance)}</strong><small>وضعیت حساب استادکار</small></article>
            </section>
            <section className="content-grid two-column">
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">پروفایل</span><h2>اطلاعات استادکار</h2></div></div><DetailList><DetailItem label="نام" value={selected.name} /><DetailItem label="نقش" value="استادکار" /><DetailItem label="تلفن" value={selected.phone || "ثبت نشده"} /><DetailItem label="شماره حساب" value={selected.account_number || "ثبت نشده"} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">تخصص</span><h2>تخصص</h2></div></div><DetailList><DetailItem label="تخصص / role_detail" value={specialty(selected)} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">کار</span><h2>کارکرد / مقدار انجام‌شده</h2></div></div><DetailList><DetailItem label="میزان کارکرد" value={state?.total_quantity ?? "۰"} /><DetailItem label="واحد کارکرد" value={state?.unit ?? "ثبت نشده"} /><DetailItem label="تعداد ثبت کار" value={`${personWorkLogs.length.toLocaleString("fa-IR")} مورد`} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">مالی</span><h2>پرداخت‌ها و فاکتورها</h2></div></div><DetailList><DetailItem label="مجموع پرداختی" value={money(paidOut)} /><DetailItem label="مانده حساب" value={money(balance)} /></DetailList><PaymentList payments={outgoingPayments} />{personInvoices.length > 0 && <InvoiceList invoices={personInvoices} />}</article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">ارتباط</span><h2>پروژه‌های مرتبط</h2></div></div><DetailList><DetailItem label="پروژه" value="پروژه فعال فعلی" /></DetailList></article>
            </section>
          </>
        )}

        {kind === "VENDOR" && (
          <>
            <section className="summary-grid">
              <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>مجموع خرید / فاکتورها</span><strong>{money(invoiceTotal + directPurchaseTotal)}</strong><small>{personInvoices.length} فاکتور</small></article>
              <article className="metric-card negative"><Wallet aria-hidden="true" /><span>مجموع پرداختی</span><strong>{money(paidOut)}</strong><small>{outgoingPayments.length} پرداخت</small></article>
              <article className={vendorDebt > 0 ? "metric-card negative" : "metric-card positive"}><CreditCard aria-hidden="true" /><span>بدهی باز</span><strong>{money(vendorDebt)}</strong><small>{vendorDebt > 0 ? "پرداخت‌نشده" : "بدون بدهی باز"}</small></article>
              <article className="metric-card"><CreditCard aria-hidden="true" /><span>مانده حساب</span><strong>{money(balance)}</strong><small>وضعیت حساب فروشنده</small></article>
            </section>
            <section className="content-grid two-column">
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">پروفایل</span><h2>اطلاعات فروشنده</h2></div></div><DetailList><DetailItem label="نام" value={selected.name} /><DetailItem label="نقش" value="فروشنده" /><DetailItem label="تلفن" value={selected.phone || "ثبت نشده"} /><DetailItem label="شماره حساب" value={selected.account_number || "ثبت نشده"} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">فاکتور</span><h2>فاکتورها</h2></div></div><DetailList><DetailItem label="مجموع فاکتورها" value={money(invoiceTotal)} /></DetailList><InvoiceList invoices={personInvoices} /></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">پرداخت</span><h2>پرداخت‌ها</h2></div></div><PaymentList payments={outgoingPayments} /></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">بدهی</span><h2>بدهی باز</h2></div></div><DetailList><DetailItem label="بدهی باز" value={money(vendorDebt)} /><DetailItem label="مانده حساب" value={money(balance)} /></DetailList></article>
              <article className="panel-card"><div className="section-title"><div><span className="eyebrow">ارتباط</span><h2>پروژه‌های مرتبط</h2></div></div><DetailList><DetailItem label="پروژه" value="پروژه فعال فعلی" /></DetailList></article>
            </section>
          </>
        )}

        {kind === "OTHER" && (
          <section className="content-grid two-column">
            <article className="panel-card"><div className="section-title"><div><span className="eyebrow">پروفایل</span><h2>اطلاعات فرد</h2></div></div><DetailList><DetailItem label="نام" value={selected.name} /><DetailItem label="نقش" value="سایر" /><DetailItem label="تلفن" value={selected.phone || "ثبت نشده"} /><DetailItem label="شماره حساب" value={selected.account_number || "ثبت نشده"} /></DetailList></article>
            <article className="panel-card"><div className="section-title"><div><span className="eyebrow">ارتباط</span><h2>پروژه‌های مرتبط</h2></div></div><DetailList><DetailItem label="پروژه" value="پروژه فعال فعلی" /></DetailList></article>
          </section>
        )}
      </div>
    );
  }

  const groups = [
    { title: "کارفرماها", Icon: Users, items: workers.filter((worker) => personKind(worker) === "CLIENT") },
    { title: "کارگرها", Icon: UserRound, items: workers.filter((worker) => personKind(worker) === "DAILY_WORKER") },
    { title: "استادکارها", Icon: Hammer, items: workers.filter((worker) => personKind(worker) === "SKILLED_WORKER") },
    { title: "فروشنده‌ها", Icon: Building2, items: workers.filter((worker) => personKind(worker) === "VENDOR") },
    { title: "سایر", Icon: UserRound, items: workers.filter((worker) => personKind(worker) === "OTHER") },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <span className="eyebrow">افراد</span>
          <h1>افراد پروژه</h1>
          <p>نمایش نقش‌محور کارفرماها، کارگرها، استادکارها و فروشنده‌ها.</p>
        </div>
        <label className="project-selector">
          <span>پروژه</span>
          <select value={selectedProjectId ?? ""} onChange={(event) => onProjectChange(Number(event.target.value))} disabled={projects.length === 0}>
            {projects.length === 0 && <option value="">پروژه‌ای وجود ندارد</option>}
            {projects.length > 0 && !selectedProjectId && <option value="">انتخاب پروژه</option>}
            {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}
          </select>
        </label>
      </section>

      {groups.map((group) => {
        const GroupIcon = group.Icon;
        return (
          <section className="panel-card" key={group.title}>
            <div className="section-title"><div><span className="eyebrow inline-icon"><GroupIcon aria-hidden="true" size={18} />{group.title}</span><h2>{group.items.length} نفر</h2></div></div>
            <div className="person-grid">
              {group.items.map((worker) => {
                const kind = personKind(worker);
                const state = workerStates.find((item) => item.worker_id === worker.id);
                const personPayments = payments.filter((payment) => payment.entity_id === worker.id);
                const paidOut = paymentTotal(personPayments, ["OUTGOING"]);
                const clientPaid = paymentTotal(personPayments, ["INCOMING"]);
                const workerWorkLogs = workLogs.filter((workLog) => workLog.worker_id === worker.id);
                const workLogDays = workerWorkLogs.reduce((total, workLog) => total + Number(workLog.unit === "day" ? workLog.quantity || 0 : 0), 0);
                const workLogLaborCost = workerWorkLogs.reduce((total, workLog) => total + Number(workLog.total_amount || 0), 0);
                const balance = kind === "DAILY_WORKER" ? workLogLaborCost - paidOut : Number(state?.financial_balance ?? 0);
                const personInvoices = invoices.filter((invoice) => invoice.vendor_id === worker.id);
                const invoiceTotal = personInvoices.reduce((total, invoice) => total + Number(invoice.total_amount || 0), 0);
                const directPurchaseTotal = personPayments
                  .filter((payment) => payment.direction === "OUTGOING" && payment.related_invoice_id === null)
                  .reduce((total, payment) => total + Number(payment.amount || 0), 0);
                const vendorDebt = Number(summary?.vendor_debts.find((debt) => debt.vendor_id === worker.id)?.debt ?? 0);
                const fundingNeed = Number(summary?.total_paid_out ?? 0) + Number(summary?.open_payables ?? 0);
                const receivable = Number(summary?.client_receivable ?? 0);
                const available = Number(summary?.available_balance ?? 0);
                const status = kind === "CLIENT"
                  ? clientStatus(summary)
                  : kind === "VENDOR"
                    ? vendorStatus(vendorDebt)
                    : workerStatus(balance);

                return (
                  <button className="person-card clickable-card" key={worker.id} type="button" onClick={() => onOpenPerson(worker.id)}>
                    <div className="person-card-header">
	                      <div><strong>{worker.name}</strong><span>{personDisplayRole(worker)}</span></div>
                      <mark className={status.badgeClassName}>{status.label}</mark>
                    </div>
                    <DetailList>
                      <DetailItem label="تلفن" value={worker.phone || "ثبت نشده"} />
                      <DetailItem label="شماره حساب" value={worker.account_number || "ثبت نشده"} />
                      {kind === "CLIENT" && <><DetailItem label="پرداخت‌شده توسط کارفرما" value={money(clientPaid)} /><DetailItem label="هزینه / نیاز مالی پروژه" value={money(fundingNeed)} /><DetailItem label="طلب پروژه از کارفرما" value={money(receivable)} /><DetailItem label="موجودی قابل خرج پروژه" value={money(available)} /></>}
                      {kind === "DAILY_WORKER" && <><DetailItem label="تعداد روز کارکرد" value={workLogDays.toLocaleString("fa-IR")} /><DetailItem label="مبلغ کارکرد" value={money(workLogLaborCost)} /><DetailItem label="دستمزد روزانه" value={worker.daily_rate ? money(worker.daily_rate) : "دستمزد روزانه ثبت نشده"} /><DetailItem label="مجموع پرداختی" value={money(paidOut)} /><DetailItem label="مانده حساب" value={money(balance)} /></>}
                      {kind === "SKILLED_WORKER" && <><DetailItem label="تخصص" value={specialty(worker)} /><DetailItem label="میزان کارکرد" value={state?.total_quantity ?? "۰"} /><DetailItem label="واحد کارکرد" value={state?.unit ?? "ثبت نشده"} /><DetailItem label="مجموع پرداختی" value={money(paidOut)} /><DetailItem label="مانده حساب" value={money(balance)} /></>}
                      {kind === "VENDOR" && <><DetailItem label="مجموع خرید / فاکتورها" value={money(invoiceTotal + directPurchaseTotal)} /><DetailItem label="مجموع پرداختی" value={money(paidOut)} /><DetailItem label="بدهی باز" value={money(vendorDebt)} /><DetailItem label="مانده حساب" value={money(balance)} /></>}
                    </DetailList>
                  </button>
                );
              })}
              {group.items.length === 0 && <p className="empty-state">هنوز موردی ثبت نشده است.</p>}
            </div>
          </section>
        );
      })}
    </div>
  );
}
