type AuthButtonProps = {
  children: string;
  loading: boolean;
  loadingText: string;
};

export function AuthButton({ children, loading, loadingText }: AuthButtonProps) {
  return (
    <button className="primary-action auth-submit" type="submit" disabled={loading}>
      {loading ? loadingText : children}
    </button>
  );
}
