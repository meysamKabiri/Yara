import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, FinalTaskObject, ProjectTask, ProjectTaskCreateResponse } from "../api";

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

export function TasksPage() {
  const params = useMemo(() => new URLSearchParams(window.location.search), []);
  const projectId = Number(params.get("project_id"));
  const initialText = params.get("text")?.trim() ?? "";
  const [text, setText] = useState(initialText);
  const [tasks, setTasks] = useState<ProjectTask[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function loadTasks() {
    if (!projectId) {
      setMessage("برای نمایش کارها، project_id را در آدرس وارد کنید.");
      return;
    }
    setIsLoading(true);
    setMessage(null);
    try {
      setTasks(await api.listProjectTasks(projectId));
    } catch {
      setMessage("دریافت فهرست کارها ناموفق بود.");
    } finally {
      setIsLoading(false);
    }
  }

  async function createTask(event: FormEvent) {
    event.preventDefault();
    const title = text.trim();
    if (!projectId || !title) return;
    setIsLoading(true);
    setMessage(null);
    try {
      const response = await api.createProjectTask(projectId, { title, raw_text: title });
      const finalTask = finalTaskFromResponse(response);
      setTasks((items) => [
        { ...response.task, final_task_object: finalTask ?? response.task.final_task_object },
        ...items,
      ]);
      setText("");
    } catch {
      setMessage("ثبت کار ناموفق بود.");
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    loadTasks();
  }, []);

  return (
    <div className="page-stack tasks-page">
      <section className="page-heading">
        <div>
          <span className="eyebrow">TaskOrchestrator</span>
          <h1>کارها</h1>
        </div>
      </section>

      <form className="panel-card task-create-form" onSubmit={createTask}>
        <label>
          متن کار
          <input
            value={text}
            onChange={(event) => setText(event.target.value)}
            placeholder="امروز مش رحیم بیاد نخاله ها رو جمع کنه"
            disabled={!projectId || isLoading}
          />
        </label>
        <button type="submit" disabled={!projectId || !text.trim() || isLoading}>
          ثبت کار
        </button>
      </form>

      {isLoading && <p className="empty-state">در حال دریافت...</p>}
      {message && <p className="empty-state">{message}</p>}
      {!isLoading && !message && tasks.length === 0 && <p className="empty-state">کاری ثبت نشده است.</p>}

      <section className="task-final-list">
        {tasks.map((task) => {
          const finalTask = finalTaskFromPersisted(task);
          return (
            <article className="panel-card task-final-card" key={task.id}>
              <div className="task-final-card-head">
                <strong>{fieldText(finalTask.title ?? task.title, "بدون عنوان")}</strong>
                {(finalTask.flags?.needs_user_confirmation || task.status === "PENDING") && (
                  <span className="task-status-badge">نیاز به بررسی</span>
                )}
              </div>
              <dl className="task-final-details">
                <div>
                  <dt>مسئول</dt>
                  <dd>{fieldText(finalTask.assignee?.name)}</dd>
                </div>
                <div>
                  <dt>زمان انجام</dt>
                  <dd>{fieldText(finalTaskDueDate(finalTask) ?? task.due_date)}</dd>
                </div>
                <div>
                  <dt>اطمینان</dt>
                  <dd>{confidenceText(finalTask.confidence ?? task.confidence)}</dd>
                </div>
              </dl>
            </article>
          );
        })}
      </section>
    </div>
  );
}
