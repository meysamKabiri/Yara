import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2, Loader2, Sparkles, X } from "lucide-react";

type JobState = "IDLE" | "SUBMITTED" | "PROCESSING" | "DONE" | "FAILED";

interface AiProcessingStatusProps {
  jobState: JobState;
  error: string | null;
  onRetry: () => void;
  onClose: () => void;
}

const steps = [
  "خواندن متن شما",
  "تشخیص افراد و مبالغ",
  "دسته‌بندی پرداخت‌ها، بدهی‌ها و کارکردها",
  "آماده‌سازی کارت‌های قابل تایید",
];

const STEP_INTERVAL = 2200;

export function AiProcessingStatus({ jobState, error, onRetry, onClose }: AiProcessingStatusProps) {
  const [stepIndex, setStepIndex] = useState(0);

  useEffect(() => {
    if (jobState === "SUBMITTED" || jobState === "PROCESSING") {
      setStepIndex(0);
      const timer = setInterval(() => {
        setStepIndex((prev) => Math.min(prev + 1, steps.length - 1));
      }, STEP_INTERVAL);
      return () => clearInterval(timer);
    }
    setStepIndex(steps.length - 1);
  }, [jobState]);

  const isProcessing = jobState === "SUBMITTED" || jobState === "PROCESSING";
  const isDone = jobState === "DONE";
  const isFailed = jobState === "FAILED";

  return (
    <div className="ai-processing-overlay" role="dialog" aria-modal="true" aria-label="پردازش هوشمند">
      <div className="ai-processing-backdrop" onClick={isDone ? onClose : undefined} />
      <div className="ai-processing-card modal-shell">
        <div className="ai-processing-header modal-header">
          <div className="ai-processing-icon-wrap">
            {isProcessing && <Sparkles className="ai-sparkle-icon" size={28} />}
            {isDone && <CheckCircle2 className="ai-done-icon" size={28} />}
            {isFailed && <AlertCircle className="ai-error-icon" size={28} />}
          </div>
          <div className="ai-processing-header-text">
            <h2>
              {isProcessing && "یارا در حال بررسی متن شماست..."}
              {isDone && "تحلیل کامل شد"}
              {isFailed && "پردازش با خطا مواجه شد"}
            </h2>
            {!isProcessing && (
              <p>
                {isDone && "موارد استخراج‌شده آماده بررسی هستند"}
                {isFailed && "امکان پردازش نوشته وجود نداشت"}
              </p>
            )}
          </div>
          {!isProcessing && (
            <button className="modal-close icon-button" type="button" onClick={onClose} aria-label="بستن">
              <X aria-hidden="true" size={20} />
            </button>
          )}
        </div>

        <div className="modal-body">
          <div className="ai-processing-steps" aria-live="polite">
            {steps.map((step, i) => (
              <div
                key={i}
                className={`ai-step ${i < stepIndex ? "done" : ""} ${i === stepIndex ? "current" : ""} ${i > stepIndex ? "pending" : ""}`}
              >
                <span className="ai-step-indicator">
                  {i < stepIndex && <CheckCircle2 size={14} />}
                  {i === stepIndex && isProcessing && <Loader2 className="ai-step-spinner" size={14} />}
                  {i === stepIndex && !isProcessing && <span className="ai-step-dot" />}
                  {i > stepIndex && <span className="ai-step-dot" />}
                </span>
                <span className="ai-step-text">{step}</span>
              </div>
            ))}
          </div>

          {isProcessing && (
            <div className="ai-processing-bar-track">
              <div className="ai-processing-bar-fill" />
            </div>
          )}

          {isFailed && (
            <div className="ai-processing-error-block">
              <p className="ai-error-text">{error || "خطا در پردازش نوشته. لطفاً دوباره تلاش کنید."}</p>
            </div>
          )}
        </div>

        {isFailed && (
          <div className="modal-footer">
            <div className="modal-actions ai-error-actions">
              <button className="primary-action" type="button" onClick={onRetry}>تلاش دوباره</button>
              <button type="button" onClick={onClose}>بستن</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
