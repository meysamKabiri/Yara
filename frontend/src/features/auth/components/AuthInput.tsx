type AuthInputProps = {
  label: string;
  type: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
};

export function AuthInput({ label, type, value, onChange, autoComplete }: AuthInputProps) {
  return (
    <label className="auth-field">
      <span>{label}</span>
      <input
        autoComplete={autoComplete}
        dir="ltr"
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
