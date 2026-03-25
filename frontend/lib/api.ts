const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ??
  (typeof window !== "undefined" ? "" : "http://localhost:8000");

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json() as Promise<T>;
}

export interface Status {
  chatwoot_connected: boolean;
  db_connected: boolean;
  openai_configured: boolean;
}

export interface Account {
  id: number;
  name: string;
  [key: string]: unknown;
}

export interface Inbox {
  id: number;
  name: string;
  channel_type?: string;
  [key: string]: unknown;
}

export interface Team {
  id: number;
  name: string;
  [key: string]: unknown;
}

export interface Article {
  id: number | string;
  title: string;
  locale?: string;
  content?: string;
  updated_at?: string;
  [key: string]: unknown;
}

export interface Conversation {
  id: number;
  /** Backend maps Chatwoot meta.sender into this top-level contact field */
  contact?: { id?: number; name?: string; email?: string };
  last_activity_at?: number;
  status?: string;
  inbox_id?: number;
  [key: string]: unknown;
}

export interface Message {
  id: number;
  content?: string;
  message_type?: number;
  sender?: { name?: string; type?: string };
  created_at?: number;
  [key: string]: unknown;
}

export interface OpenAIConfig {
  api_key?: string;
  model?: string;
  params?: Record<string, unknown>;
}

export function getStatus(): Promise<Status> {
  return request<Status>("/web/status");
}

export function getAccounts(): Promise<Account[]> {
  return request<Account[]>("/web/chatwoot/accounts");
}

export function getInboxes(accountId?: number): Promise<Inbox[]> {
  const q = accountId != null ? `?account_id=${accountId}` : "";
  return request<Inbox[]>(`/web/chatwoot/inboxes${q}`);
}

export function getTeams(accountId?: number): Promise<Team[]> {
  const q = accountId != null ? `?account_id=${accountId}` : "";
  return request<Team[]>(`/web/chatwoot/teams${q}`);
}

export function getHelpCenterArticles(search?: string, locale?: string): Promise<Article[]> {
  const params = new URLSearchParams();
  if (search) params.set("search", search);
  if (locale) params.set("locale", locale);
  const q = params.toString() ? `?${params}` : "";
  return request<Article[]>(`/web/chatwoot/help-center${q}`);
}

export function syncHelpCenter(accountId?: number, portalSlug?: string): Promise<{ synced: number }> {
  const body: Record<string, unknown> = {};
  if (accountId != null) body.account_id = accountId;
  if (portalSlug) body.portal_slug = portalSlug;
  return request<{ synced: number }>("/web/chatwoot/sync-help-center", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getTokenApis(): Promise<Record<string, string>> {
  return request<Record<string, string>>("/web/config/token-api");
}

export function saveTokenApi(accountId: number, tokenApi: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/web/config/token-api", {
    method: "POST",
    body: JSON.stringify({ account_id: accountId, token_api: tokenApi }),
  });
}

export function getOpenAIConfig(): Promise<OpenAIConfig> {
  return request<OpenAIConfig>("/web/config/openai");
}

export function saveOpenAIConfig(config: OpenAIConfig): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/web/config/openai", {
    method: "POST",
    body: JSON.stringify(config),
  });
}

export function getConversations(
  limit: number,
  accountId?: number,
  inboxId?: number
): Promise<Conversation[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (accountId != null) params.set("account_id", String(accountId));
  if (inboxId != null) params.set("inbox_id", String(inboxId));
  return request<Conversation[]>(`/web/conversations?${params}`);
}

export function getConversationMessages(
  conversationId: number,
  accountId?: number
): Promise<Message[]> {
  const q = accountId != null ? `?account_id=${accountId}` : "";
  return request<Message[]>(`/web/conversations/${conversationId}/messages${q}`);
}
