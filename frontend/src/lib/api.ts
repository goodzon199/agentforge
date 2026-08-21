const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8011/api/v1";

// Sprint 5.8.1 Platform Gateway: the frontend knows a single core address.
// Pack namespaces are exposed by core as /api/v1{pack_route}/... and proxied
// to the owning pack from the registry. Domain paths below are rewritten to
// the autoparts namespace; core routes them to the pack automatically.
const PACK_PREFIX = "/autoparts";

// Sprint 5.0 split: domain verticals (autoparts) moved out of core. These
// paths live in the autoparts pack and reach it through the core gateway.
const DOMAIN_PREFIXES = [
  "/manager",
  "/part_requests",
  "/quotes",
  "/orders",
  "/suppliers",
  "/supplier-orders",
  "/garage",
  "/fitment",
  "/approvals",
  "/actions",
  "/hellopack",
  "/conversations",
  "/customers",
  "/tasks",
  "/company-policies",
];

function gatewayPath(path: string): string {
  return DOMAIN_PREFIXES.some((prefix) => path.startsWith(prefix))
    ? `${PACK_PREFIX}${path}`
    : path;
}

export const TOKEN_KEY = "agentforge_token";
export const USER_KEY = "agentforge_user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function getStoredUser<T = { is_superuser?: boolean }>(): T | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return null;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}${gatewayPath(path)}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (res.status === 401) {
    clearToken();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
  }
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${detail.slice(0, 200)}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "POST", body: JSON.stringify(body) }),
  patch: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PATCH", body: JSON.stringify(body) }),
  put: <T>(path: string, body: unknown) =>
    request<T>(path, { method: "PUT", body: JSON.stringify(body) }),
  del: (path: string) => request<void>(path, { method: "DELETE" }),
};
