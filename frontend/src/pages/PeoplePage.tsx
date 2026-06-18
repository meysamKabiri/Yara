import { Building2, ChevronRight, Clock, CreditCard, Phone, ReceiptText, UserRound, Users, Wallet } from "lucide-react";
import { Invoice, OperatingSummary, Payment, Worker, WorkerState, WorkLog } from "../api";

type PeoplePageProps = {
  workers: Worker[];
  workerStates: WorkerState[];
  payments: Payment[];
  workLogs: WorkLog[];
  invoices: Invoice[];
  summary: OperatingSummary | null;
  selectedPersonId: number | null;
  onOpenPerson: (personId: number) => void;
  onBackToPeople: () => void;
};

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function roleTitle(type: Worker["type"]): string {
  const labels: Record<Worker["type"], string> = {
    DAILY_WORKER: "کارگر ساده / روزمزد",
    SKILLED_WORKER: "استادکار",
    VENDOR: "فروشنده",
    CLIENT: "کارفرما",
  };
  return labels[type];
}

function specialty(worker: Worker): string {
  return worker.role_detail || "تخصص ثبت نشده";
}

function clientFinancialStatus(fundingNeed: number, clientPaid: number) {
  const clientReceivable = Math.max(0, fundingNeed - clientPaid);
  const availableBalance = Math.max(0, clientPaid - fundingNeed);

  if (clientReceivable > 0) {
    return {
      label: "بدهکار",
      balanceLabel: "بدهی کارفرما",
      amount: clientReceivable,
      badgeClassName: "status-negative",
      cardClassName: "metric-card negative",
      hint: "طلب پروژه از کارفرما",
    };
  }

  if (availableBalance > 0) {
    return {
      label: "موجودی مثبت",
      balanceLabel: "موجودی قابل خرج",
      amount: availableBalance,
      badgeClassName: "status-positive",
      cardClassName: "metric-card positive",
      hint: "قابل خرج برای پروژه",
    };
  }

  return {
    label: "تسویه",
    balanceLabel: "موجودی قابل خرج",
    amount: 0,
    badgeClassName: "status-pending",
    cardClassName: "metric-card pending",
    hint: "بدون بدهی یا موجودی",
  };
}

function workerFinancialStatus(balance: number) {
  return {
    label: balance > 0 ? "طلبکار" : balance < 0 ? "بدهکار" : "تسویه",
    badgeClassName: balance > 0 ? "status-positive" : balance < 0 ? "status-negative" : "status-pending",
  };
}

export function PeoplePage({ workers, workerStates, payments, workLogs, invoices, summary, selectedPersonId, onOpenPerson, onBackToPeople }: PeoplePageProps) {
  const selected = selectedPersonId ? workers.find((worker) => worker.id === selectedPersonId) : null;

  if (selected) {
    const state = workerStates.find((item) => item.worker_id === selected.id);
    const personPayments = payments.filter((payment) => payment.entity_id === selected.id);
    const clientPayments = personPayments.filter((payment) => payment.direction === "INCOMING");
    const personInvoices = invoices.filter((invoice) => invoice.vendor_id === selected.id);
    const paid = personPayments.reduce((total, payment) => total + Number(payment.amount || 0), 0);
    const invoiceTotal = personInvoices.reduce((total, invoice) => total + Number(invoice.total_amount || 0), 0);
    const isClient = selected.type === "CLIENT";
    const isVendor = selected.type === "VENDOR";
    const isWorker = selected.type === "DAILY_WORKER" || selected.type === "SKILLED_WORKER";
    const vendorDebt = Number(summary?.vendor_debts.find((debt) => debt.vendor_id === selected.id)?.debt ?? 0);
    const clientPaid = clientPayments.reduce((total, payment) => total + Number(payment.amount || 0), 0);
    const fundingNeed = Number(summary?.total_paid_out ?? 0) + Number(summary?.open_payables ?? 0);
    const clientStatus = clientFinancialStatus(fundingNeed, clientPaid);
    const availableBalance = Math.max(0, clientPaid - fundingNeed);

    return (
      <div className="page-stack">
        <section className="project-topbar">
          <button className="icon-button" type="button" onClick={onBackToPeople} aria-label="بازگشت"><ChevronRight aria-hidden="true" size={22} /></button>
          <div>
            <span className="eyebrow">جزئیات فرد</span>
            <h1>{selected.name}</h1>
            <p className="muted">{roleTitle(selected.type)}{selected.role_detail ? ` · ${selected.role_detail}` : ""}</p>
          </div>
        </section>

        <section className="summary-grid five-up">
          <article className="metric-card"><UserRound aria-hidden="true" /><span>نقش</span><strong>{roleTitle(selected.type)}</strong><small>نقش در پروژه فعلی</small></article>
          {isClient && (
            <>
              <article className="metric-card positive"><Wallet aria-hidden="true" /><span>پرداخت‌شده توسط کارفرما</span><strong>{money(clientPaid)}</strong><small>ورودی پروژه</small></article>
              <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>هزینه/نیاز مالی پروژه</span><strong>{money(fundingNeed)}</strong><small>پرداختی‌ها + بدهی باز</small></article>
              <article className={clientStatus.cardClassName}><CreditCard aria-hidden="true" /><span>{clientStatus.balanceLabel}</span><strong>{money(clientStatus.amount)}</strong><small>{clientStatus.hint}</small></article>
              <article className="metric-card positive"><Wallet aria-hidden="true" /><span>موجودی قابل خرج پروژه</span><strong>{money(availableBalance)}</strong><small>مازاد دریافتی پروژه</small></article>
            </>
          )}
          {isWorker && (
            <>
              {selected.type === "SKILLED_WORKER" ? (
                <>
                  <article className="metric-card pending"><Clock aria-hidden="true" /><span>میزان کارکرد</span><strong>{state?.total_quantity ?? "۰"}</strong><small>{state?.unit ?? "بدون واحد"}</small></article>
                  <article className="metric-card pending"><Clock aria-hidden="true" /><span>واحد کارکرد</span><strong>{state?.unit ?? "بدون واحد"}</strong><small>{specialty(selected)}</small></article>
                </>
              ) : (
                <article className="metric-card pending"><Clock aria-hidden="true" /><span>تعداد روز کارکرد</span><strong>{state?.total_days_worked ?? "۰"}</strong><small>روزمزد / حضور</small></article>
              )}
              <article className="metric-card negative"><Wallet aria-hidden="true" /><span>مجموع پرداختی</span><strong>{money(paid)}</strong><small>{personPayments.length} پرداخت</small></article>
              <article className="metric-card"><CreditCard aria-hidden="true" /><span>مانده حساب</span><strong>{money(state?.financial_balance)}</strong><small>وضعیت مالی فرد</small></article>
            </>
          )}
          {isVendor && (
            <>
              <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>مجموع خرید/پرداختی</span><strong>{money(invoiceTotal + paid)}</strong><small>{personInvoices.length} فاکتور · {personPayments.length} پرداخت</small></article>
              <article className="metric-card pending"><ReceiptText aria-hidden="true" /><span>فاکتورها</span><strong>{money(invoiceTotal)}</strong><small>{personInvoices.length} فاکتور</small></article>
              <article className={vendorDebt > 0 ? "metric-card negative" : "metric-card positive"}><CreditCard aria-hidden="true" /><span>بدهی باز</span><strong>{money(vendorDebt)}</strong><small>{vendorDebt > 0 ? "بدهی به فروشنده" : "بدون بدهی باز"}</small></article>
              <article className="metric-card"><CreditCard aria-hidden="true" /><span>مانده حساب</span><strong>{money(state?.financial_balance)}</strong><small>وضعیت مالی فروشنده</small></article>
            </>
          )}
        </section>

        <section className="content-grid two-column">
          <article className="panel-card">
            <div className="section-title"><div><span className="eyebrow">پروفایل</span><h2>اطلاعات فرد</h2></div></div>
            <dl className="detail-list">
              <div><dt><UserRound aria-hidden="true" size={15} />نام</dt><dd>{selected.name}</dd></div>
              <div><dt><Phone aria-hidden="true" size={15} />تلفن</dt><dd>{selected.phone || "ثبت نشده"}</dd></div>
              <div><dt><CreditCard aria-hidden="true" size={15} />شماره حساب</dt><dd>{selected.account_number || "ثبت نشده"}</dd></div>
              {isClient && <div><dt>موجودی قابل خرج پروژه</dt><dd>{money(availableBalance)}</dd></div>}
            </dl>
          </article>

          {isClient && (
            <article className="panel-card">
              <div className="section-title"><div><span className="eyebrow">ارتباط پروژه</span><h2>پروژه‌های مرتبط</h2></div></div>
              <dl className="detail-list">
                <div><dt><Building2 aria-hidden="true" size={15} />پروژه</dt><dd>پروژه فعال فعلی</dd></div>
                <div><dt>وضعیت</dt><dd>{clientStatus.label}</dd></div>
                <div><dt>{clientStatus.balanceLabel}</dt><dd>{money(clientStatus.amount)}</dd></div>
              </dl>
            </article>
          )}

          <article className="panel-card">
            <div className="section-title"><div><span className="eyebrow">سابقه پرداخت</span><h2>{isClient ? "پرداخت‌های کارفرما" : "پرداخت‌های اخیر"}</h2></div></div>
            <div className="mini-list">
              {(isClient ? clientPayments : personPayments).map((payment) => <div className="mini-row" key={payment.id}><strong>{money(payment.amount)}</strong><span>{payment.direction}</span></div>)}
              {(isClient ? clientPayments : personPayments).length === 0 && <p className="empty-state">پرداختی برای این فرد ثبت نشده است.</p>}
            </div>
          </article>
        </section>
      </div>
    );
  }

  const groups = [
    { title: "کارگرها", Icon: UserRound, items: workers.filter((worker) => worker.type === "DAILY_WORKER") },
    { title: "استادکارها", Icon: UserRound, items: workers.filter((worker) => worker.type === "SKILLED_WORKER") },
    { title: "فروشنده‌ها", Icon: Building2, items: workers.filter((worker) => worker.type === "VENDOR") },
    { title: "کارفرماها", Icon: Users, items: workers.filter((worker) => worker.type === "CLIENT") },
  ];

  return (
    <div className="page-stack">
      <section className="page-heading">
        <div>
          <span className="eyebrow">افراد</span>
          <h1>افراد پروژه‌ها</h1>
          <p>کارگرها، استادکارها، فروشنده‌ها و کارفرماها همراه با وضعیت حساب و پرداخت‌ها.</p>
        </div>
      </section>

      {groups.map((group) => {
        const GroupIcon = group.Icon;
        return (
        <section className="panel-card" key={group.title}>
          <div className="section-title"><div><span className="eyebrow inline-icon"><GroupIcon aria-hidden="true" size={18} />{group.title}</span><h2>{group.items.length} نفر</h2></div></div>
          <div className="person-grid">
            {group.items.map((worker) => {
              const state = workerStates.find((item) => item.worker_id === worker.id);
              const paid = payments.filter((payment) => payment.entity_id === worker.id).reduce((total, payment) => total + Number(payment.amount || 0), 0);
              const balance = Number(state?.financial_balance ?? 0);
              const isClient = worker.type === "CLIENT";
              const isVendor = worker.type === "VENDOR";
              const vendorDebt = Number(summary?.vendor_debts.find((debt) => debt.vendor_id === worker.id)?.debt ?? 0);
              const invoiceTotal = invoices.filter((invoice) => invoice.vendor_id === worker.id).reduce((total, invoice) => total + Number(invoice.total_amount || 0), 0);
              const fundingNeed = Number(summary?.total_paid_out ?? 0) + Number(summary?.open_payables ?? 0);
              const clientPaid = payments
                .filter((payment) => payment.entity_id === worker.id && payment.direction === "INCOMING")
                .reduce((total, payment) => total + Number(payment.amount || 0), 0);
              const clientStatus = clientFinancialStatus(fundingNeed, clientPaid);
              const personStatus = isClient ? clientStatus : workerFinancialStatus(balance);
              return (
                <button className="person-card clickable-card" key={worker.id} type="button" onClick={() => onOpenPerson(worker.id)}>
                  <div className="person-card-header">
                    <div><strong>{worker.name}</strong><span>{roleTitle(worker.type)}{worker.role_detail ? ` · ${worker.role_detail}` : ""}</span></div>
                    <mark className={personStatus.badgeClassName}>{personStatus.label}</mark>
                  </div>
                  <dl className="detail-list">
                    <div><dt>تلفن</dt><dd>{worker.phone || "ثبت نشده"}</dd></div>
                    <div><dt>شماره حساب</dt><dd>{worker.account_number || "ثبت نشده"}</dd></div>
                    {isClient ? (
                      <>
                        <div><dt>پرداخت‌شده توسط کارفرما</dt><dd>{money(clientPaid)}</dd></div>
                        <div><dt>{clientStatus.balanceLabel}</dt><dd>{money(clientStatus.amount)}</dd></div>
                      </>
                    ) : isVendor ? (
                      <>
                        <div><dt>مجموع خرید/پرداختی</dt><dd>{money(invoiceTotal + paid)}</dd></div>
                        <div><dt>فاکتورها</dt><dd>{money(invoiceTotal)}</dd></div>
                        <div><dt>بدهی باز</dt><dd>{money(vendorDebt)}</dd></div>
                        <div><dt>مانده حساب</dt><dd>{money(balance)}</dd></div>
                      </>
                    ) : (
                      <>
                        {worker.type === "SKILLED_WORKER" ? (
                          <>
                            <div><dt>تخصص</dt><dd>{specialty(worker)}</dd></div>
                            <div><dt>میزان کارکرد</dt><dd>{state?.total_quantity ?? "۰"}</dd></div>
                            <div><dt>واحد</dt><dd>{state?.unit ?? "بدون واحد"}</dd></div>
                            <div><dt>مجموع پرداختی</dt><dd>{money(paid)}</dd></div>
                          </>
                        ) : (
                          <>
                            <div><dt>تعداد روز کارکرد</dt><dd>{state?.total_days_worked ?? "۰"}</dd></div>
                            <div><dt>دستمزد/پرداختی</dt><dd>{money(paid)}</dd></div>
                          </>
                        )}
                        <div><dt>مانده حساب</dt><dd>{money(balance)}</dd></div>
                      </>
                    )}
                    <div><dt>وضعیت</dt><dd>{personStatus.label}</dd></div>
                  </dl>
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
