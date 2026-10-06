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

/** Confirm an address from the emailed token. Idempotent; 400 on invalid/expired. */
export async function verifyEmail(token: string): Promise<void> {
  await plainClient.post("/auth/verify-email", { token });
}

/** Email the signed-in user a fresh link. Both 202 ("sent") and 200 ("already verified") are success. */
export async function resendVerification(): Promise<void> {
  await http.post("/auth/resend-verification");
}

/** Request a reset (or set-password) email. The server always answers 202, whether or not the account exists. */
export async function forgotPassword(email: string): Promise<void> {
  await plainClient.post("/auth/forgot-password", { email });
}

/** Choose a new password from the emailed token. Success revokes every session. */
export async function resetPassword(input: { token: string; newPassword: string }): Promise<void> {
  await plainClient.post("/auth/reset-password", {
    token: input.token,
    new_password: input.newPassword,
  });
}

/** Absolute URL that starts the Google flow; must be opened by full-page navigation, never XHR. */
export function googleStartUrl(baseUrl: string): string {
  return `${baseUrl}/auth/google`;
}

/** Change the display name. Never send `null`: the server treats it as a no-op. */
export async function updateName(name: string): Promise<User> {
  const { data } = await http.patch<User>("/auth/me", { name });
  return data;
}

/**
 * Erase the account. DELETE carries a JSON body (G-12). The password is required only for
 * accounts that have one; Google-only accounts omit it.
 */
export async function deleteAccount(password?: string): Promise<void> {
  await http.delete("/auth/me", { data: password ? { password } : {} });
}
