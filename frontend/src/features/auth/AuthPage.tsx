import { useState } from "react";
import { authApi, AUTH_TOKEN_KEY } from "./authApi";
import { AuthForm } from "./components/AuthForm";
import { AuthMode, AuthUser } from "./types";

type AuthPageProps = {
  onAuthenticated: (user: AuthUser) => void;
};

export function AuthPage({ onAuthenticated }: AuthPageProps) {
  const [mode, setMode] = useState<AuthMode>("login");

  async function submit(email: string, password: string) {
    const result = mode === "login"
      ? await authApi.login(email, password)
      : await authApi.signup(email, password);

    localStorage.setItem(AUTH_TOKEN_KEY, result.access_token);
    onAuthenticated(result.user);
  }

  function toggleMode() {
    setMode((current) => (current === "login" ? "signup" : "login"));
  }

  return (
    <main className="auth-shell" dir="rtl">
      <AuthForm mode={mode} onSubmit={submit} onToggleMode={toggleMode} />
    </main>
  );
}
