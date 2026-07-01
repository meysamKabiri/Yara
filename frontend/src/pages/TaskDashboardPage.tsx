import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, FinalTaskObject, ProjectTask, ProjectTaskCreateResponse, Worker } from "../api";

type TaskTab = "today" | "upcoming" | "all" | "review";

const TABS: Array<{ key: TaskTab; label: string }> = [
  { key: "today", label: "امروز" },
  { key: "upcoming", label: "آینده" },
  { key: "all", label: "همه" },
  { key: "review", label: "نیاز به بررسی" },
];

function todayIso(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function fieldText(value: unknown, fallback = "ثبت نشده"): string {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return value.toLocaleString("fa-IR");
  return fallback;
}

function confidenceText(value: unknown): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "ثبت نشده";
  return `${Math.round(value * 100).toLocaleString("fa-IR")}٪`;
}

function finalTaskFromResponse(response: ProjectTaskCreateResponse): FinalTaskObject | null {
  const finalTask = response.final_task_object;
  if (!finalTask || typeof finalTask !== "object" || Array.isArray(finalTask)) return null;
  return finalTask as FinalTaskObject;
}

function finalTaskFromPersisted(task: ProjectTask): FinalTaskObject {
  if (task.final_task_object) return task.final_task_object;
  return {
    title: task.title,
    assignee: { name: task.assignee_suggestion?.suggested_person?.name ?? null },
    due_date: task.due_date,
    confidence: task.confidence ?? task.due_date_confidence,
    flags: { needs_user_confirmation: task.status !== "CONFIRMED" },
  };
}

function finalTaskDueDate(finalTask: FinalTaskObject): string | null {
  if (typeof finalTask.due_date === "string" && finalTask.due_date.trim()) return finalTask.due_date.trim();
  if (finalTask.due_date && typeof finalTask.due_date === "object") return finalTask.due_date.value ?? null;
  return null;
}

function taskDueDate(task: ProjectTask): string | null {
  return finalTaskDueDate(finalTaskFromPersisted(task)) ?? task.due_date ?? null;
}

function needsReview(task: ProjectTask): boolean {
  return Boolean(finalTaskFromPersisted(task).flags?.needs_user_confirmation);
}

function taskAssigneeName(task: ProjectTask, workers: Worker[]): string {
  const fromFinalTask = finalTaskFromPersisted(task).assignee?.name;
  if (fromFinalTask) return fromFinalTask;
  const worker = workers.find((item) => item.id === task.assignee_id);
  return worker?.name ?? task.assignee_suggestion?.suggested_person?.name ?? "ثبت نشده";
}

function statusLabel(status: string): string {
  if (status === "COMPLETED") return "انجام‌شده";
  if (status === "CONFIRMED") return "تأیید شده";
  return "در انتظار";
}

export function TaskDashboardPage({ projectId: projectIdProp }: { projectId?: number | null }) {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const projectId = projectIdProp ?? Number(params.get("project_id"));
  const [activeTab, setActiveTab] = useState<TaskTab>("today");
  const [text, setText] = useState("");
  const [tasks, setTasks] = useState<ProjectTask[]>([]);
  const [workers, setWorkers] = useState<Worker[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const filteredTasks = useMemo(() => {
    const today = todayIso();
    if (activeTab === "today") return tasks.filter((task) => taskDueDate(task) === today);
    if (activeTab === "upcoming") return tasks.filter((task) => {
      const dueDate = taskDueDate(task);
      return Boolean(dueDate && dueDate > today);
    });
    if (activeTab === "review") return tasks.filter(needsReview);
    return tasks;
  }, [activeTab, tasks]);

  async function loadData() {
    if (!projectId) {
      setError("برای نمایش کارها، project_id را در آدرس وارد کنید.");
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const [taskList, workerList] = await Promise.all([
        api.listProjectTasks(projectId),
        api.listWorkers(projectId),
      ]);
      setTasks(taskList);
      setWorkers(workerList);
    } catch {
      setError("دریافت کارها ناموفق بود.");
    } finally {
      setIsLoading(false);
    }
  }

  async function createTask(event: FormEvent) {
    event.preventDefault();
    const title = text.trim();
    if (!projectId || !title) return;
    setIsLoading(true);
    setError(null);
    try {
      const response = await api.createProjectTask(projectId, { title, raw_text: title });
      const finalTask = finalTaskFromResponse(response);
      setTasks((items) => [
        { ...response.task, final_task_object: finalTask ?? response.task.final_task_object },
        ...items,
      ]);
      setText("");
    } catch {
      setError("ثبت کار ناموفق بود.");
    } finally {
      setIsLoading(false);
    }
  }

  async function updateTask(taskId: number, payload: { status?: string; assignee_id?: number | null; due_date?: string | null }) {
    setError(null);
    try {
      const updated = await api.updateProjectTask(taskId, payload);
      setTasks((items) => items.map((task) => (task.id === taskId ? updated : task)));
    } catch {
      setError("به‌روزرسانی کار ناموفق بود.");
    }
  }

  useEffect(() => {
    loadData();
  }, [projectId]);

  return (
    <div className="page-stack task-dashboard-page">
      <section className="page-heading">
        <div>
          <span className="eyebrow">کارها</span>
          <h1>داشبورد کارها</h1>
        </div>
      </section>

      <form className="panel-card task-dashboard-create" onSubmit={createTask}>
        <label>
          متن کار
          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="امروز مش رحیم بیاد نخاله ها رو جمع کنه"
            disabled={!projectId || isLoading}
            rows={3}
          />
        </label>
        <button type="submit" disabled={!projectId || !text.trim() || isLoading}>
          Create Task
        </button>
      </form>

      <div className="task-dashboard-tabs" role="tablist" aria-label="Task filters">
        {TABS.map((tab) => (
          <button
            className={activeTab === tab.key ? "active" : ""}
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {isLoading && <p className="empty-state">در حال دریافت...</p>}
      {error && <p className="empty-state">{error}</p>}
      {!isLoading && !error && filteredTasks.length === 0 && <p className="empty-state">هیچ کاری وجود ندارد</p>}

      <section className="task-dashboard-list">
        {filteredTasks.map((task) => {
          const finalTask = finalTaskFromPersisted(task);
          const dueDate = taskDueDate(task);
          return (
            <article className="panel-card task-dashboard-card" key={task.id}>
              <div className="task-dashboard-card-head">
                <strong>{fieldText(finalTask.title ?? task.title, "بدون عنوان")}</strong>
                <span className={`task-state-badge ${task.status === "CONFIRMED" || task.status === "COMPLETED" ? "confirmed" : "pending"}`}>
                  {statusLabel(task.status)}
                </span>
              </div>

              <div className="task-dashboard-meta">
                <span>مسئول: {taskAssigneeName(task, workers)}</span>
                <span>زمان: {fieldText(dueDate)}</span>
                <span>اطمینان: {confidenceText(finalTask.confidence ?? task.confidence)}</span>
              </div>

              <div className="task-dashboard-actions">
                <button type="button" onClick={() => updateTask(task.id, { status: "COMPLETED" })}>
                  Mark as Done
                </button>
                <label>
                  Edit Assignee
                  <select
                    value={task.assignee_id ?? ""}
                    onChange={(event) => updateTask(task.id, { assignee_id: event.target.value ? Number(event.target.value) : null })}
                  >
                    <option value="">بدون مسئول</option>
                    {workers.map((worker) => (
                      <option key={worker.id} value={worker.id}>{worker.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Edit Due Date
                  <input
                    type="date"
                    value={dueDate ?? ""}
                    onChange={(event) => updateTask(task.id, { due_date: event.target.value || null })}
                  />
                </label>
              </div>
            </article>
          );
        })}
      </section>
    </div>
  );
}
