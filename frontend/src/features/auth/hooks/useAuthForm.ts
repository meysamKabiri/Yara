import { useState } from "react";
import { AuthFormValues, AuthMode } from "../types";

const initialValues: AuthFormValues = {
  email: "",
  password: "",
  confirmPassword: "",
};

export function useAuthForm(mode: AuthMode) {
  const [values, setValues] = useState<AuthFormValues>(initialValues);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function updateField(field: keyof AuthFormValues, value: string) {
    setValues((current) => ({ ...current, [field]: value }));
    if (error) setError(null);
  }

  function validate() {
    const email = values.email.trim();
    if (!email || !values.password) {
      setError("ایمیل و رمز عبور الزامی است.");
      return false;
    }

    if (mode === "signup" && values.password !== values.confirmPassword) {
      setError("رمز عبور و تکرار آن یکسان نیست.");
      return false;
    }

    setError(null);
    return true;
  }

  function reset() {
    setValues(initialValues);
    setError(null);
  }

  return {
    values,
    updateField,
    validate,
    loading,
    setLoading,
    error,
    setError,
    reset,
  };
}
