import { FormEvent, useMemo, useRef, useState } from "react";
import { ArrowDownCircle, ArrowUpCircle, BriefcaseBusiness, Clock, FolderKanban, Hammer, Plus, Search, Scale, UserRound, Wallet } from "lucide-react";
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
          <button className="primary-action with-icon" type="button" onClick={() => setIsCreateOpen(true)}><Plus aria-hidden="true" size={18} />پروژه جدید</button>
        </div>
        <label className="project-search">
          <Search aria-hidden="true" size={17} />
          <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="جستجوی پروژه" />
        </label>
        <div className="project-card-grid overview-cards">
          {visibleProjects.map((project) => {
            const financials = projectFinancials[project.id] ?? { received: 0, paid: 0, net: 0, debt: 0, labor: 0, pending: 0, deferred: 0, clientName: null, lastActivity: project.updated_at };
            const status = projectStatus(financials);
            return (
              <article className="project-card project-overview-card" key={project.id}>
                <div className="project-card-head">
                  <div>
                    <strong>{project.name}</strong>
                    <span><Clock aria-hidden="true" size={13} />آخرین فعالیت: {new Date(financials.lastActivity ?? project.updated_at).toLocaleDateString("fa-IR")}</span>
                    <span><UserRound aria-hidden="true" size={13} />کارفرما: {financials.clientName ?? "ثبت نشده"}</span>
                  </div>
                  <mark className={status.className}>{status.label}</mark>
                </div>
                <dl>
                  <div><dt><ArrowDownCircle aria-hidden="true" size={15} />دریافتی</dt><dd className="money-positive">{money(financials.received)}</dd></div>
                  <div><dt><ArrowUpCircle aria-hidden="true" size={15} />پرداختی</dt><dd className="money-negative">{money(financials.paid)}</dd></div>
                  <div><dt><Wallet aria-hidden="true" size={15} />بدهی باز</dt><dd className={financials.debt > 0 ? "money-pending" : ""}>{money(financials.debt)}</dd></div>
                  <div><dt><Hammer aria-hidden="true" size={15} />کارکرد</dt><dd>{money(financials.labor)}</dd></div>
                  <div><dt><Scale aria-hidden="true" size={15} />مانده</dt><dd className={financials.net >= 0 ? "money-positive" : "money-negative"}>{money(financials.net)}</dd></div>
                  <div><dt>در انتظار تایید</dt><dd className={financials.pending > 0 ? "money-pending" : ""}>{financials.pending.toLocaleString("fa-IR")}</dd></div>
                </dl>
                <div className="project-card-actions">
                  <button className="primary-action" type="button" onClick={() => onOpenProject(project.id)}>باز کردن</button>
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
          <form className="confirmation-modal create-project-modal" onSubmit={submitCreate}>
            <div className="modal-header">
              <div>
                <span className="eyebrow">پروژه جدید</span>
                <h2>ایجاد پروژه</h2>
                <p>فعلا فقط نام پروژه ذخیره می‌شود. کارفرما را می‌توانید بعدا با ورودی هوشمند اضافه کنید.</p>
              </div>
              <button type="button" onClick={() => setIsCreateOpen(false)}>بستن</button>
            </div>
            <label>
              <span>نام پروژه</span>
              <input ref={projectNameInputRef} value={projectName} onChange={(event) => onProjectNameChange(event.target.value)} placeholder="مثلا ویلا دماوند" autoFocus />
            </label>
            <label>
              <span>توضیح اختیاری</span>
              <textarea disabled placeholder="در نسخه فعلی ذخیره نمی‌شود" />
            </label>
            <div className="modal-actions">
              <button type="button" onClick={() => setIsCreateOpen(false)}>انصراف</button>
              <button className="primary-action with-icon" type="submit" disabled={isLoading || !projectName.trim()}><Plus aria-hidden="true" size={18} />ایجاد پروژه</button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
