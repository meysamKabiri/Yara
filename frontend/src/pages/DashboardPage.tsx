import { FormEvent, useRef } from "react";
import { ArrowDownCircle, ArrowUpCircle, BriefcaseBusiness, FolderKanban, Plus, Scale, Wallet } from "lucide-react";
import { Project } from "../api";

type ProjectFinancials = {
  received: number;
  paid: number;
  net: number;
  debt: number;
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

  return (
    <div className="page-stack home-page">
      <section className="home-hero">
        <div className="home-hero-copy">
          <h1>دفتر مالی هوشمند پروژه‌ها</h1>
          <p>ثبت کنید، تأیید کنید و همیشه از وضعیت مالی پروژه مطلع باشید.</p>
        </div>
      </section>

      <form className="create-project-card" onSubmit={onCreateProject}>
        <label>
          <span>ایجاد پروژه جدید</span>
          <input ref={projectNameInputRef} value={projectName} onChange={(event) => onProjectNameChange(event.target.value)} placeholder="نام پروژه" />
        </label>
        <button className="primary-action with-icon" type="submit" disabled={isLoading || !projectName.trim()}><Plus aria-hidden="true" size={18} />ایجاد پروژه</button>
      </form>

      <section className="project-overview-section">
        <div className="section-title">
          <div>
            <span className="eyebrow inline-icon"><BriefcaseBusiness aria-hidden="true" size={17} />پروژه‌ها</span>
            <h2>پروژه‌ها</h2>
          </div>
        </div>
        <div className="project-card-grid overview-cards">
          {projects.map((project) => {
            const financials = projectFinancials[project.id] ?? { received: 0, paid: 0, net: 0, debt: 0 };
            const status = projectStatus(financials);
            return (
              <button className="project-card project-overview-card" key={project.id} type="button" onClick={() => onOpenProject(project.id)}>
                <div className="project-card-head">
                  <div>
                    <strong>{project.name}</strong>
                    <span>آخرین بروزرسانی: {new Date(project.updated_at).toLocaleDateString("fa-IR")}</span>
                  </div>
                  <mark className={status.className}>{status.label}</mark>
                </div>
                <dl>
                  <div><dt><ArrowDownCircle aria-hidden="true" size={15} />دریافتی</dt><dd className="money-positive">{money(financials.received)}</dd></div>
                  <div><dt><ArrowUpCircle aria-hidden="true" size={15} />پرداختی</dt><dd className="money-negative">{money(financials.paid)}</dd></div>
                  <div><dt><Scale aria-hidden="true" size={15} />مانده</dt><dd className={financials.net >= 0 ? "money-positive" : "money-negative"}>{money(financials.net)}</dd></div>
                  <div><dt><Wallet aria-hidden="true" size={15} />بدهی باز</dt><dd className={financials.debt > 0 ? "money-pending" : ""}>{money(financials.debt)}</dd></div>
                </dl>
              </button>
            );
          })}
          {projects.length === 0 && (
            <div className="empty-state home-empty-state">
              <FolderKanban aria-hidden="true" size={36} />
              <strong>هنوز پروژه‌ای ایجاد نشده است</strong>
              <span>برای شروع، اولین پروژه خود را ایجاد کنید.</span>

            </div>
          )}
        </div>
      </section>
    </div>
  );
}
