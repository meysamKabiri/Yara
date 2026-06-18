import { FormEvent } from "react";
import { AlertTriangle, ArrowDownCircle, ArrowUpCircle, Plus, Scale, Wallet } from "lucide-react";
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

export function DashboardPage({ projects, projectFinancials, projectName, isLoading, onProjectNameChange, onCreateProject, onOpenProject }: DashboardPageProps) {
  const openDebtCount = Object.values(projectFinancials).filter((item) => item.debt > 0).length;

  return (
    <div className="page-stack home-page">
      <section className="home-hero">
        <div>
          <span className="eyebrow">Yara</span>
          <h1>مدیریت مالی پروژه‌ها بدون شلوغی دفتر و اکسل</h1>
          <p>پروژه را باز کنید، اتفاقات را به یارا بگویید، تایید کنید و حساب‌ها همیشه مرتب می‌مانند.</p>
        </div>
        <div className="notification-card">
          <AlertTriangle aria-hidden="true" size={22} />
          <span>هشدارها</span>
          <strong>{openDebtCount}</strong>
          <small>پروژه‌های دارای بدهی باز</small>
        </div>
      </section>

      <form className="create-project-card" onSubmit={onCreateProject}>
        <label>
          <span>ایجاد پروژه</span>
          <input value={projectName} onChange={(event) => onProjectNameChange(event.target.value)} placeholder="نام پروژه جدید" />
        </label>
        <button className="primary-action with-icon" type="submit" disabled={isLoading || !projectName.trim()}><Plus aria-hidden="true" size={18} />ایجاد پروژه</button>
      </form>

      <section className="project-overview-section">
        <div className="section-title">
          <div>
            <span className="eyebrow">خانه</span>
            <h2>پروژه‌ها</h2>
          </div>
        </div>
        <div className="project-card-grid overview-cards">
          {projects.map((project) => {
            const financials = projectFinancials[project.id] ?? { received: 0, paid: 0, net: 0, debt: 0 };
            return (
              <button className="project-card project-overview-card" key={project.id} type="button" onClick={() => onOpenProject(project.id)}>
                <div>
                  <strong>{project.name}</strong>
                  <span>{new Date(project.updated_at).toLocaleDateString("fa-IR")}</span>
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
          {projects.length === 0 && <p className="empty-state">اولین پروژه را ایجاد کنید تا ثبت کار و حساب‌ها شروع شود.</p>}
        </div>
      </section>
    </div>
  );
}
