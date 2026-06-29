import { FormEvent } from "react";
import { Mic, Send } from "lucide-react";
import { Project } from "../api";
import { MONEY_UNIT_HELPER, MULTI_ACTION_WARNING, looksLikeMultiAction } from "../ui/betaSafety";

export type AskInteraction = {
  id: string;
  text: string;
  createdAt: string;
  interpretationCount: number;
};

type AskYaraPageProps = {
  project: Project | null;
  text: string;
  examples: string[];
  interactions: AskInteraction[];
  isLoading: boolean;
  onTextChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onVoicePlaceholder: () => void;
};

export function AskYaraPage({ project, text, examples, interactions, isLoading, onTextChange, onSubmit, onVoicePlaceholder }: AskYaraPageProps) {
  return (
    <div className="page-stack ask-page">
      <section className="page-heading">
        <div>
          <span className="eyebrow">Ask Yara</span>
          <h1>به یارا بگویید چه اتفاقی افتاد</h1>
          <p>اتفاقات پروژه را فارسی و طبیعی بنویسید. بدون فرم و بدون دفتر شلوغ.</p>
        </div>
        <mark className="project-pill">{project ? project.name : "پروژه‌ای انتخاب نشده"}</mark>
      </section>

      <section className="ask-composer panel-card">
        <form onSubmit={onSubmit}>
          <textarea value={text} onChange={(event) => onTextChange(event.target.value)} placeholder="مثلا: میثم ۲۰۰ میلیون برای شروع پروژه پول داد" />
          <div className="composer-actions">
            <button type="button" onClick={onVoicePlaceholder} aria-label="ضبط صدا"><Mic aria-hidden="true" size={20} /></button>
            <button className="primary-action" type="submit" disabled={isLoading || !project || !text.trim()} aria-label="ارسال"><Send aria-hidden="true" size={20} /></button>
          </div>
        </form>
        <p className="input-helper-text">{MONEY_UNIT_HELPER}</p>
        {looksLikeMultiAction(text) && <p className="warning-text">{MULTI_ACTION_WARNING}</p>}
        <div className="example-chip-list">
          {examples.map((example) => <button key={example} type="button" onClick={() => onTextChange(example)}>{example}</button>)}
        </div>
      </section>

      <section className="panel-card">
        <div className="section-title"><div><span className="eyebrow">تاریخچه</span><h2>تعامل‌های اخیر</h2></div></div>
        <div className="record-grid">
          {interactions.map((interaction) => (
            <article className="record-card" key={interaction.id}>
              <div><strong>{interaction.interpretationCount} برداشت</strong><span>{new Date(interaction.createdAt).toLocaleString("fa-IR")}</span></div>
              <p>{interaction.text}</p>
            </article>
          ))}
          {interactions.length === 0 && <p className="empty-state">تاریخچه تعامل‌های این نشست اینجا نمایش داده می‌شود.</p>}
        </div>
      </section>
    </div>
  );
}
