import { FormEvent, useEffect, useState } from "react";
import { api, CounterpartyType, EventType, EventUpdate, ExtractedEvent, Project, ProjectDetail, RawEntry } from "./api";

const eventTypes: EventType[] = ["MONEY_IN", "MONEY_OUT", "PURCHASE", "NOTE"];
const counterpartyTypes: CounterpartyType[] = ["CUSTOMER", "VENDOR", "WORKER", "UNKNOWN"];

function blankEventUpdate(event: ExtractedEvent): EventUpdate {
  return {
    type: event.type,
    amount: event.amount ?? "",
    counterparty_name: event.counterparty_name ?? "",
    counterparty_type: event.counterparty_type,
    description: event.description ?? "",
    event_date: event.event_date ?? "",
  };
}

function cleanEventUpdate(form: EventUpdate): EventUpdate {
  return {
    ...form,
    amount: form.amount === "" ? null : form.amount,
    counterparty_name: form.counterparty_name === "" ? null : form.counterparty_name,
    description: form.description === "" ? null : form.description,
    event_date: form.event_date === "" ? null : form.event_date,
  };
}

function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectName, setProjectName] = useState("");
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [pendingEvents, setPendingEvents] = useState<ExtractedEvent[]>([]);
  const [confirmedEvents, setConfirmedEvents] = useState<ExtractedEvent[]>([]);
  const [rawNote, setRawNote] = useState("");
  const [lastRawEntry, setLastRawEntry] = useState<RawEntry | null>(null);
  const [editingEventId, setEditingEventId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState<EventUpdate | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadProjects();
  }, []);

  useEffect(() => {
    if (selectedProjectId) {
      loadProjectData(selectedProjectId);
    }
  }, [selectedProjectId]);

  async function runAction(action: () => Promise<void>) {
    setLoading(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setLoading(false);
    }
  }

  async function loadProjects() {
    await runAction(async () => {
      setProjects(await api.listProjects());
    });
  }

  async function loadProjectData(projectId: number) {
    await runAction(async () => {
      const [detail, pending, confirmed] = await Promise.all([
        api.getProject(projectId),
        api.listPendingEvents(projectId),
        api.listConfirmedEvents(projectId),
      ]);
      setProjectDetail(detail);
      setPendingEvents(pending);
      setConfirmedEvents(confirmed);
    });
  }

  async function createProject(event: FormEvent) {
    event.preventDefault();
    const name = projectName.trim();
    if (!name) return;

    await runAction(async () => {
      const project = await api.createProject(name);
      setProjectName("");
      setProjects(await api.listProjects());
      setSelectedProjectId(project.id);
    });
  }

  async function submitRawNote(event: FormEvent) {
    event.preventDefault();
    if (!selectedProjectId || !rawNote.trim()) return;

    await runAction(async () => {
      const rawEntry = await api.createRawEntry(selectedProjectId, rawNote.trim());
      setLastRawEntry(rawEntry);
      setRawNote("");
    });
  }

  async function extractLastRawEntry() {
    if (!selectedProjectId || !lastRawEntry) return;

    await runAction(async () => {
      await api.extractRawEntry(selectedProjectId, lastRawEntry.id);
      setLastRawEntry(null);
      await loadProjectData(selectedProjectId);
    });
  }

  function startEditing(event: ExtractedEvent) {
    setEditingEventId(event.id);
    setEditForm(blankEventUpdate(event));
  }

  async function saveEdit(eventId: number) {
    if (!selectedProjectId || !editForm) return;

    await runAction(async () => {
      await api.updateEvent(eventId, cleanEventUpdate(editForm));
      setEditingEventId(null);
      setEditForm(null);
      await loadProjectData(selectedProjectId);
    });
  }

  async function confirmEvent(eventId: number) {
    if (!selectedProjectId) return;

    await runAction(async () => {
      await api.confirmEvent(eventId);
      await loadProjectData(selectedProjectId);
    });
  }

  async function discardEvent(eventId: number) {
    if (!selectedProjectId) return;

    await runAction(async () => {
      await api.discardEvent(eventId);
      setEditingEventId(null);
      setEditForm(null);
      await loadProjectData(selectedProjectId);
    });
  }

  return (
    <main className="app">
      <header>
        <h1>Yara Phase 1 MVP</h1>
        <p>Project → Raw Note → Extract → Pending Cards → Confirm → Totals</p>
      </header>

      {error && <div className="error">{error}</div>}
      {loading && <div className="loading">Working...</div>}

      <section className="panel">
        <h2>Projects</h2>
        <form className="row" onSubmit={createProject}>
          <input value={projectName} onChange={(event) => setProjectName(event.target.value)} placeholder="New project name" />
          <button type="submit" disabled={loading}>Create project</button>
        </form>

        <div className="list">
          {projects.map((project) => (
            <button
              className={project.id === selectedProjectId ? "project selected" : "project"}
              key={project.id}
              onClick={() => setSelectedProjectId(project.id)}
              type="button"
            >
              Open {project.name}
            </button>
          ))}
          {projects.length === 0 && <p>No projects yet.</p>}
        </div>
      </section>

      {projectDetail && (
        <section className="panel">
          <h2>{projectDetail.name}</h2>
          <p className="notice">Totals include confirmed money events only. Pending and discarded events do not affect totals.</p>
          <div className="totals">
            <div><span>Money In</span><strong>{projectDetail.totals.money_in}</strong></div>
            <div><span>Money Out</span><strong>{projectDetail.totals.money_out}</strong></div>
            <div><span>Net</span><strong>{projectDetail.totals.net}</strong></div>
          </div>

          <form className="raw-note" onSubmit={submitRawNote}>
            <label htmlFor="raw-note">Raw note</label>
            <textarea id="raw-note" value={rawNote} onChange={(event) => setRawNote(event.target.value)} placeholder="Client paid me 1200 for cabinets" />
            <button type="submit" disabled={loading}>Submit raw note</button>
          </form>

          {lastRawEntry && (
            <div className="extract-box">
              <div>
                <strong>Raw entry #{lastRawEntry.id} saved.</strong>
                <p>{lastRawEntry.text}</p>
              </div>
              <button type="button" onClick={extractLastRawEntry} disabled={loading}>Run extraction</button>
            </div>
          )}

          <h3>Pending extracted events</h3>
          <p className="pending-rule">Pending cards are review items only. They are excluded from totals until confirmed.</p>
          <div className="cards">
            {pendingEvents.map((event) => (
              <PendingEventCard
                key={event.id}
                event={event}
                editForm={editingEventId === event.id ? editForm : null}
                onStartEdit={startEditing}
                onEditChange={setEditForm}
                onCancelEdit={() => { setEditingEventId(null); setEditForm(null); }}
                onSaveEdit={saveEdit}
                onConfirm={confirmEvent}
                onDiscard={discardEvent}
                loading={loading}
              />
            ))}
            {pendingEvents.length === 0 && <p>No pending events.</p>}
          </div>

          <h3>Confirmed events</h3>
          <div className="confirmed-list">
            {confirmedEvents.map((event) => (
              <EventSummary key={event.id} event={event} />
            ))}
            {confirmedEvents.length === 0 && <p>No confirmed events.</p>}
          </div>
        </section>
      )}
    </main>
  );
}

type PendingEventCardProps = {
  event: ExtractedEvent;
  editForm: EventUpdate | null;
  onStartEdit: (event: ExtractedEvent) => void;
  onEditChange: (form: EventUpdate) => void;
  onCancelEdit: () => void;
  onSaveEdit: (eventId: number) => void;
  onConfirm: (eventId: number) => void;
  onDiscard: (eventId: number) => void;
  loading: boolean;
};

function PendingEventCard({ event, editForm, onStartEdit, onEditChange, onCancelEdit, onSaveEdit, onConfirm, onDiscard, loading }: PendingEventCardProps) {
  const isEditing = editForm !== null;

  return (
    <article className="card pending-card">
      <div className="card-header">
        <strong>Pending event #{event.id}</strong>
        <span>raw_entry_id: {event.raw_entry_id}</span>
      </div>

      {isEditing ? (
        <div className="edit-grid">
          <label>Type<select value={editForm.type} onChange={(e) => onEditChange({ ...editForm, type: e.target.value as EventType })}>{eventTypes.map((type) => <option key={type}>{type}</option>)}</select></label>
          <label>Amount<input value={editForm.amount ?? ""} onChange={(e) => onEditChange({ ...editForm, amount: e.target.value })} /></label>
          <label>Counterparty name<input value={editForm.counterparty_name ?? ""} onChange={(e) => onEditChange({ ...editForm, counterparty_name: e.target.value })} /></label>
          <label>Counterparty type<select value={editForm.counterparty_type} onChange={(e) => onEditChange({ ...editForm, counterparty_type: e.target.value as CounterpartyType })}>{counterpartyTypes.map((type) => <option key={type}>{type}</option>)}</select></label>
          <label>Description<textarea value={editForm.description ?? ""} onChange={(e) => onEditChange({ ...editForm, description: e.target.value })} /></label>
          <label>Event date<input type="date" value={editForm.event_date ?? ""} onChange={(e) => onEditChange({ ...editForm, event_date: e.target.value })} /></label>
        </div>
      ) : (
        <EventFields event={event} />
      )}

      <div className="actions">
        {isEditing ? (
          <>
            <button type="button" onClick={() => onSaveEdit(event.id)} disabled={loading}>Save edit</button>
            <button type="button" onClick={onCancelEdit} disabled={loading}>Cancel</button>
          </>
        ) : (
          <button type="button" onClick={() => onStartEdit(event)} disabled={loading}>Edit</button>
        )}
        <button type="button" onClick={() => onConfirm(event.id)} disabled={loading}>Confirm</button>
        <button type="button" onClick={() => onDiscard(event.id)} disabled={loading}>Discard</button>
      </div>
    </article>
  );
}

function EventFields({ event }: { event: ExtractedEvent }) {
  return (
    <dl className="fields">
      <div><dt>type</dt><dd>{event.type}</dd></div>
      <div><dt>amount</dt><dd>{event.amount ?? "-"}</dd></div>
      <div><dt>counterparty_name</dt><dd>{event.counterparty_name ?? "-"}</dd></div>
      <div><dt>counterparty_type</dt><dd>{event.counterparty_type}</dd></div>
      <div><dt>description</dt><dd>{event.description ?? "-"}</dd></div>
      <div><dt>confidence</dt><dd>{event.confidence ?? "-"}</dd></div>
      <div><dt>event_date</dt><dd>{event.event_date ?? "-"}</dd></div>
      <div><dt>raw_entry_id</dt><dd>{event.raw_entry_id}</dd></div>
    </dl>
  );
}

function EventSummary({ event }: { event: ExtractedEvent }) {
  return (
    <article className="card confirmed-card">
      <div className="card-header"><strong>{event.type}</strong><span>{event.amount ?? "no amount"}</span></div>
      <p>{event.description ?? "No description"}</p>
      <small>raw_entry_id: {event.raw_entry_id} · status: {event.status}</small>
    </article>
  );
}

export default App;
