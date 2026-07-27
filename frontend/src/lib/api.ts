import type { Campaign, Finding, Sweep, Target, User } from "./types";

export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const TOKEN_KEY = "asclepius_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    throw new ApiError(res.status, `Request to ${path} failed (${res.status})`);
  }
  return (await res.json()) as T;
}

/** Exchange credentials for a bearer token and persist it. */
export async function login(email: string, password: string): Promise<string> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ username: email, password }),
  });
  if (!res.ok) {
    throw new ApiError(res.status, "Invalid email or password");
  }
  const data = (await res.json()) as { access_token: string };
  setToken(data.access_token);
  return data.access_token;
}

export type DashboardStats = {
  targets: number;
  activeSweeps: number;
  openFindings: number;
  pendingReview: number;
};

export const api = {
  me: () => request<User>("/auth/me"),
  dashboard: () => request<DashboardStats>("/dashboard"),
  targets: () => request<Target[]>("/targets"),
  target: (id: string) => request<Target>(`/targets/${id}`),
  campaigns: () => request<Campaign[]>("/campaigns"),
  campaign: (id: string) => request<Campaign>(`/campaigns/${id}`),
  sweeps: () => request<Sweep[]>("/sweeps"),
  sweep: (id: string) => request<Sweep>(`/sweeps/${id}`),
  findings: () => request<Finding[]>("/findings"),
  finding: (id: string) => request<Finding>(`/findings/${id}`),
  review: () => request<Finding[]>("/review"),
};
