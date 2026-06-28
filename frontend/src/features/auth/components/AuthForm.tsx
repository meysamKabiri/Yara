import { FormEvent } from "react";
import { AuthMode } from "../types";
import { useAuthForm } from "../hooks/useAuthForm";
import { AuthButton } from "./AuthButton";
import { AuthInput } from "./AuthInput";

type AuthFormProps = {
  mode: AuthMode;
  onSubmit: (email: string, password: string) => Promise<void>;
  onToggleMode: () => void;
};

export function AuthForm({ mode, onSubmit, onToggleMode }: AuthFormProps) {
  const form = useAuthForm(mode);
  const isSignup = mode === "signup";

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.validate()) return;

    form.setLoading(true);
    form.setError(null);
    try {
      await onSubmit(form.values.email.trim(), form.values.password);
      form.reset();
    } catch (err) {
      form.setError(err instanceof Error ? err.message : "خطایی رخ داد. دوباره تلاش کنید.");
    } finally {
      form.setLoading(false);
    }
  }

  return (
    <form className="auth-card" onSubmit={submit}>
      <div className="auth-card-header">
        <strong>Yara</strong>
        <h1>{isSignup ? "ساخت حساب" : "ورود"}</h1>
      </div>

      <AuthInput
        autoComplete="email"
        label="ایمیل"
        type="email"
        value={form.values.email}
        onChange={(value) => form.updateField("email", value)}
      />

      <AuthInput
        autoComplete={isSignup ? "new-password" : "current-password"}
        label="رمز عبور"
        type="password"
        value={form.values.password}
        onChange={(value) => form.updateField("password", value)}
      />

      {isSignup && (
        <AuthInput
          autoComplete="new-password"
          label="تکرار رمز عبور"
          type="password"
          value={form.values.confirmPassword}
          onChange={(value) => form.updateField("confirmPassword", value)}
        />
      )}

      {form.error && <div className="error-banner">{form.error}</div>}

      <AuthButton loading={form.loading} loadingText={isSignup ? "در حال ساخت حساب..." : "در حال ورود..."}>
        {isSignup ? "ساخت حساب" : "ورود"}
      </AuthButton>

      <button className="text-button auth-toggle" type="button" onClick={onToggleMode} disabled={form.loading}>
        {isSignup ? "حساب دارید؟ ورود" : "حساب ندارید؟ ساخت حساب"}
      </button>
    </form>
  );
}
