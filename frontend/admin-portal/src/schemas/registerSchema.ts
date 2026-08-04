import { z } from "zod";

const USERNAME_REGEX = /^[a-zA-Z0-9._-]+$/;
const REGISTERABLE_ROLES = ["admin", "developer", "platform_engineer"] as const;

export const registerSchema = z
  .object({
    first_name: z.string().trim().min(1, "First name is required").max(64),
    last_name: z.string().trim().min(1, "Last name is required").max(64),
    username: z
      .string()
      .trim()
      .min(3, "Username must be at least 3 characters")
      .max(64)
      .regex(USERNAME_REGEX, "Use letters, numbers, dots, hyphens, or underscores"),
    email: z.string().trim().email("Enter a valid email address"),
    password: z.string().min(8, "Password must be at least 8 characters"),
    confirm_password: z.string().min(1, "Please confirm your password"),
    role: z.enum(REGISTERABLE_ROLES),
  })
  .refine((data) => data.password === data.confirm_password, {
    message: "Passwords do not match",
    path: ["confirm_password"],
  });

export type RegisterFields = z.infer<typeof registerSchema>;