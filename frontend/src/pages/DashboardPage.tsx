import { FormEvent, useMemo, useRef, useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, BriefcaseBusiness, ChevronDown, ChevronUp, Clock, FolderKanban, Plus, Search, Scale, UserRound, Wallet, X } from "lucide-react";
import { Project } from "../api";

type ProjectFinancials = {
  received: number;
  paid: number;
  net: number;
  debt: number;
  labor: number;
  pending: number;
  deferred: number;
  clientName: string | null;
  lastActivity: string | null;
};

type DashboardPageProps = {
  projects: Project[];
  projectFinancials: Record<number, ProjectFinancials>;
  projectName: string;
  isLoading: boolean;
  onProjectNameChange: (value: string) => void;
  onCreateProject: (event: FormEvent) => void;
  onOpenProject: (projectId: number) => void;
};

function money(value: string | number | null | undefined): string {
  return `${Number(value ?? 0).toLocaleString("fa-IR")} تومان`;
}

function projectStatus(financials: ProjectFinancials) {
  if (financials.net < 0) return { label: "بدهکار", className: "status-negative" };
  if (financials.debt > 0) return { label: "نیاز به پرداخت", className: "status-pending" };
  return { label: "سالم", className: "status-positive" };
}

export function DashboardPage({ projects, projectFinancials, projectName, isLoading, onProjectNameChange, onCreateProject, onOpenProject }: DashboardPageProps) {
  const projectNameInputRef = useRef<HTMLInputElement>(null);
  const [search, setSearch] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [expandedProjectId, setExpandedProjectId] = useState<number | null>(null);
  const visibleProjects = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return projects;
    return projects.filter((project) => project.name.toLowerCase().includes(needle));
  }, [projects, search]);

  function submitCreate(event: FormEvent) {
    onCreateProject(event);
    if (projectName.trim()) setIsCreateOpen(false);
  }

  return (
    <div className="page-stack home-page">
      <section className="home-hero">
        <div className="home-hero-copy">
          <h1>دفتر مالی هوشمند پروژه‌ها</h1>
          <p>ثبت کنید، تأیید کنید و همیشه از وضعیت مالی پروژه مطلع باشید.</p>
        </div>
      </section>

      <section className="project-overview-section">
        <div className="section-title project-list-title">
          <div>
            <span className="eyebrow inline-icon"><BriefcaseBusiness aria-hidden="true" size={17} />پروژه‌ها</span>
            <h2>پروژه‌ها</h2>
          </div>
          <button className="primary-action create-project-trigger with-icon" type="button" onClick={() => setIsCreateOpen(true)}><Plus aria-hidden="true" size={18} />پروژه جدید</button>
        </div>
        <label className="project-search">
          <Search aria-hidden="true" size={17} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="جستجوی پروژه" />
        </label>
        <div className="project-card-grid overview-cards">
          {visibleProjects.map((project) => {
            const financials = projectFinancials[project.id] ?? { received: 0, paid: 0, net: 0, debt: 0, labor: 0, pending: 0, deferred: 0, clientName: null, lastActivity: project.updated_at };
            const status = projectStatus(financials);
            const isExpanded = expandedProjectId === project.id;
            const createdAt = new Date(project.created_at).toLocaleDateString("fa-IR");
            const lastActivity = new Date(financials.lastActivity ?? project.updated_at).toLocaleDateString("fa-IR");
            const cashBalance = financials.received - financials.paid;
            return (
              <article
                className={`project-card project-overview-card${isExpanded ? " is-expanded" : ""}`}
                key={project.id}
              >
                <div className="project-card-head">
                  <button
                    className="project-card-toggle"
                    type="button"
                    onClick={() => setExpandedProjectId((current) => current === project.id ? null : project.id)}
                    aria-expanded={isExpanded}
                    aria-label={`${isExpanded ? "بستن کارت پروژه" : "باز کردن کارت پروژه"} ${project.name}`}
                  >
                    <strong>{project.name}</strong>
                    {isExpanded ? <ChevronUp className="project-card-chevron" aria-hidden="true" size={18} /> : <ChevronDown className="project-card-chevron" aria-hidden="true" size={18} />}
                  </button>
                  <div className="project-card-identity">
                    <span className="desktop-project-dates"><Clock aria-hidden="true" size={13} />ایجاد: {createdAt} · آخرین فعالیت: {lastActivity}</span>
                    <span className="mobile-project-date"><Clock aria-hidden="true" size={13} />آخرین فعالیت: {lastActivity}</span>
                    <span><UserRound aria-hidden="true" size={13} />کارفرما: {financials.clientName ?? "ثبت نشده"}</span>
                  </div>
                  <mark className={`project-card-status ${status.className}`}>{status.label}</mark>
                </div>
                <dl className="project-card-details">
                  <div><dt><ArrowDownCircle aria-hidden="true" size={15} />دریافتی</dt><dd className="money-positive">{money(financials.received)}</dd></div>
                  <div><dt><ArrowUpCircle aria-hidden="true" size={15} />پرداخت‌شده</dt><dd className="money-negative">{money(financials.paid)}</dd></div>
                  <div><dt><Scale aria-hidden="true" size={15} />موجودی نقدی پروژه</dt><dd className={cashBalance >= 0 ? "money-positive" : "money-negative"}>{money(cashBalance)}</dd></div>
                  <div><dt><Wallet aria-hidden="true" size={15} />بدهی باز</dt><dd className={financials.debt > 0 ? "money-pending" : ""}>{money(financials.debt)}</dd></div>
                  <div className="project-created-row"><dt>تاریخ ایجاد</dt><dd>{createdAt}</dd></div>
                </dl>
                <div className="project-card-actions">
                  <button className="project-card-link" type="button" onClick={() => onOpenProject(project.id)}>مشاهده پروژه</button>
                </div>
              </article>
            );
          })}
          {projects.length > 0 && visibleProjects.length === 0 && <div className="empty-state home-empty-state"><Search aria-hidden="true" size={30} /><strong>پروژه‌ای با این جستجو پیدا نشد</strong></div>}
          {projects.length === 0 && (
            <div className="empty-state home-empty-state">
              <FolderKanban aria-hidden="true" size={36} />
              <strong>هنوز پروژه‌ای ایجاد نشده است</strong>
              <span>برای شروع، اولین پروژه خود را ایجاد کنید.</span>
            </div>
          )}
        </div>
      </section>

      {isCreateOpen && (
        <div className="modal-backdrop">
          <form className="confirmation-modal modal-shell create-project-modal" onSubmit={submitCreate}>
            <div className="modal-header">
              <div>
                <h2 className="modal-title">ایجاد پروژه</h2>
                <p>فعلاً فقط نام پروژه ذخیره می‌شود. کارفرما و جزئیات را می‌توانید بعداً با ورودی هوشمند اضافه کنید.</p>
              </div>
              <button className="modal-close icon-button" type="button" onClick={() => setIsCreateOpen(false)} aria-label="بستن">
                <X aria-hidden="true" size={20} />
              </button>
            </div>
            <div className="modal-body">
              <label>
                <span>نام پروژه</span>
                <input ref={projectNameInputRef} value={projectName} onChange={(event) => onProjectNameChange(event.target.value)} placeholder="مثلا ویلا دماوند" autoFocus />
              </label>
              <label>
                <span>توضیح اختیاری</span>
                <textarea disabled placeholder="پس از ایجاد پروژه از ویرایش پروژه اضافه کنید" />
              </label>
            </div>
            <div className="modal-footer">
              <div className="modal-actions">
              <button className="primary-action with-icon" type="submit" disabled={isLoading || !projectName.trim()}><Plus aria-hidden="true" size={18} />ایجاد پروژه</button>
                <button type="button" onClick={() => setIsCreateOpen(false)}>انصراف</button>
              </div>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
