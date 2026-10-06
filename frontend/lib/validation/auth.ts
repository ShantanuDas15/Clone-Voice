import { z } from "zod";

/** Mirrors backend bounds (`schemas/auth.py`, `validators.py`); the server stays authoritative. */
export const PASSWORD_MIN = 8;
export const PASSWORD_MAX = 128;
export const LOGIN_PASSWORD_MAX = 4096;
export const NAME_MAX = 255;

const email = z.string().trim().min(1, "Enter your email").email("Enter a valid email address");

export const loginSchema = z.object({
  email,
  password: z
    .string()
    .min(1, "Enter your password")
    .max(LOGIN_PASSWORD_MAX, "Password is too long"),
});

export const signupSchema = z.object({
  email,
  name: z
    .string()
    .trim()
    .min(1, "Enter your name")
    .max(NAME_MAX, `Name must be at most ${NAME_MAX} characters`),
  password: z
    .string()
    .min(PASSWORD_MIN, `Password must be at least ${PASSWORD_MIN} characters`)
    .max(PASSWORD_MAX, `Password must be at most ${PASSWORD_MAX} characters`),
});

export type LoginValues = z.infer<typeof loginSchema>;
export type SignupValues = z.infer<typeof signupSchema>;

export const forgotSchema = z.object({ email });

export const resetSchema = z
  .object({
    password: z
      .string()
      .min(PASSWORD_MIN, `Password must be at least ${PASSWORD_MIN} characters`)
      .max(PASSWORD_MAX, `Password must be at most ${PASSWORD_MAX} characters`),
    confirm: z.string(),
  })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords don't match" });

export type ForgotValues = z.infer<typeof forgotSchema>;
export type ResetValues = z.infer<typeof resetSchema>;
