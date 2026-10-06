import { http } from "@/lib/api/http";
import { plainClient } from "@/lib/api/plain";

export interface User {
  id: string;
  email: string;
  name: string;
  avatar_url: string | null;
  provider: string;
  has_password: boolean;
  email_verified_at: string | null;
  created_at: string;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
}

/** Create an account; the backend also sets the refresh cookie (FE-2). Returns the access token. */
export async function signup(input: {
  email: string;
  password: string;
  name: string;
}): Promise<string> {
  const { data } = await plainClient.post<TokenResponse>("/auth/signup", input);
  return data.access_token;
}

/** Email/password login. Returns the access token. */
export async function login(input: { email: string; password: string }): Promise<string> {
  const { data } = await plainClient.post<TokenResponse>("/auth/login", input);
  return data.access_token;
}

/** Revoke the refresh token server-side (idempotent 204). */
export async function logout(): Promise<void> {
  await plainClient.post("/auth/logout");
}

/** Current user. */
export async function fetchMe(): Promise<User> {
  const { data } = await http.get<User>("/auth/me");
  return data;
}
