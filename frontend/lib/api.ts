/**
 * Shared API client for the Tata Agent web UI.
 *
 * Since the frontend is served from the same origin as the FastAPI backend
 * (both on port 8000), all paths are relative to the current origin.
 * Set NEXT_PUBLIC_API_URL to override when developing against a remote backend.
 */

const BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? JSON.stringify(body);
    } catch {
      // ignore parse error
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface Account {
  id: number;
  name: string;
  chatwoot_account_id: number;
  is_active: boolean;
}

export interface AccountCreate {
  name: string;
  chatwoot_account_id: number;
  is_active: boolean;
}

export interface AppSettings {
  llm_model: string;
  llm_provider: string;
  openai_api_key_set: boolean;
  openai_api_endpoint: string;
  embedding_model: string;
  embedding_dimension: number;
  response_delay_seconds: number;
  log_level: string;
  webhook_token_set: boolean;
}

export interface SettingsPayload {
  llm_model?: string;
  llm_provider?: string;
  openai_api_key?: string;
  openai_api_endpoint?: string;
  embedding_model?: string;
  embedding_dimension?: number;
  response_delay_seconds?: number;
  log_level?: string;
  webhook_token?: string;
}

export interface SetupStatus {
  setup_complete: boolean;
  chatwoot_configured: boolean;
  openai_configured: boolean;
  accounts_count: number;
}

export interface Message {
  id: number;
  chatwoot_conv_id: number;
  content: string;
  status: string;
  send_attempts: number;
  created_at: string;
  error?: string;
}

export interface Article {
  id: string;
  title: string;
  content: string;
  portal_slug?: string;
}

export interface TataVariable {
  key: string;
  value: string;
  description: string;
  category: string;
  is_secret: boolean;
}

// ---------------------------------------------------------------------------
// API client objects
// ---------------------------------------------------------------------------

export const accountsApi = {
  list: () => request<Account[]>("/api/accounts"),
  create: (data: AccountCreate) =>
    request<Account>("/api/accounts", { method: "POST", body: JSON.stringify(data) }),
  update: (id: number, data: Partial<AccountCreate>) =>
    request<Account>(`/api/accounts/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  remove: (id: number) => request<void>(`/api/accounts/${id}`, { method: "DELETE" }),
  test: (id: number) =>
    request<{ ok: boolean; account_name?: string; error?: string }>(
      `/api/accounts/${id}/test`
    ),
  inboxes: (id: number) =>
    request<Record<string, unknown>[]>(`/api/accounts/${id}/inboxes`),
};

export const settingsApi = {
  get: () => request<AppSettings>("/api/settings"),
  update: (data: SettingsPayload) =>
    request<AppSettings>("/api/settings", { method: "POST", body: JSON.stringify(data) }),
  setupStatus: () => request<SetupStatus>("/api/settings/setup-status"),
};

export const variablesApi = {
  list: (category?: string) =>
    request<TataVariable[]>(category ? `/api/variables?category=${category}` : "/api/variables"),
  upsert: (vars: { key: string; value: string }[]) =>
    request<TataVariable[]>("/api/variables", { method: "POST", body: JSON.stringify(vars) }),
  update: (key: string, data: Partial<TataVariable>) =>
    request<TataVariable>(`/api/variables/${key}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
};

export const helpCenterApi = {
  articles: (params?: { search?: string; portal_slug?: string }) => {
    const qs = new URLSearchParams();
    if (params?.search) qs.set("search", params.search);
    if (params?.portal_slug) qs.set("portal_slug", params.portal_slug);
    const suffix = qs.toString() ? `?${qs}` : "";
    return request<Article[]>(`/api/helpcenter/articles${suffix}`);
  },
  sync: (account_id?: number) =>
    request<{ message: string; synced?: number }>("/api/helpcenter/sync", {
      method: "POST",
      body: JSON.stringify(account_id !== undefined ? { account_id } : {}),
    }),
};

export const conversationsApi = {
  recent: (limit = 10) =>
    request<Message[]>(`/api/conversations/messages?limit=${limit}`),
};
