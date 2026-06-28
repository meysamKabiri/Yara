export type AuthMode = "login" | "signup";

export type AuthFormValues = {
  email: string;
  password: string;
  confirmPassword: string;
};

export type AuthUser = {
  id: string;
  email: string;
  created_at: string;
};

export type AuthResponse = {
  access_token: string;
  token_type: "bearer";
  user: AuthUser;
};
