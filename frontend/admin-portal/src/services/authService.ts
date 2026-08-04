import axios from "axios";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api",
});

export interface DevLoginResponse {
  access_token: string;
}

export interface RegisterUserPayload {
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  password: string;
  role: "admin" | "developer" | "platform_engineer";
}

export interface RegisterUserResponse {
  username: string;
  email: string;
  assigned_role: string;
  message: string;
}

export async function loginUser(username: string, password: string): Promise<DevLoginResponse> {
  const { data } = await api.post<DevLoginResponse>("/auth/dev-login", { username, password });
  return data;
}

export async function registerUser(payload: RegisterUserPayload): Promise<RegisterUserResponse> {
  const { data } = await api.post<RegisterUserResponse>("/auth/dev-register", payload);
  return data;
}