import type {
  Detail, Filters, Insights, Ledger, Overview, Profile, Review, Signals, Snapshot,
} from "./types";

const TOKEN_KEY = "savia.session";

let token: string | null = sessionStorage.getItem(TOKEN_KEY);

export const hasSession = () => Boolean(token);

export function clearSession() {
  token = null;
  sessionStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body) headers.set("Content-Type", "application/json");

  const response = await fetch(`/api${path}`, { ...init, headers });
  if (response.status === 401) {
    clearSession();
    throw new ApiError(401, "session expired");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* keep the status text */
    }
    throw new ApiError(response.status, String(detail));
  }
  return response.json() as Promise<T>;
}

/** Turns the filter object into the query string the API expects. */
export function filterQuery(f: Partial<Filters>, extra: Record<string, string | number> = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(f)) {
    if (key === "flags") continue;
    if (value) params.set(key, String(value));
  }
  for (const flag of f.flags ?? []) params.append("flags", flag);
  for (const [key, value] of Object.entries(extra)) params.set(key, String(value));
  return params.toString();
}

export const api = {
  health: () => request<{ ok: boolean; build_id: string }>("/health"),
  snapshot: () => request<Snapshot>("/snapshot"),
  profiles: () => request<{ profiles: Profile[] }>("/profiles").then((r) => r.profiles),

  async signIn(slug: string) {
    const result = await request<{ token: string; expires_at: number; customer: any }>(
      "/session", { method: "POST", body: JSON.stringify({ slug }) });
    token = result.token;
    sessionStorage.setItem(TOKEN_KEY, result.token);
    return result;
  },

  overview: () => request<Overview>("/overview"),
  insights: (currency?: string) =>
    request<Insights>(`/insights${currency ? `?currency=${encodeURIComponent(currency)}` : ""}`),
  signals: () => request<Signals>("/signals"),

  ledger: (f: Partial<Filters>, offset = 0, limit = 40) =>
    request<Ledger>(`/transactions?${filterQuery(f, { offset, limit })}`),

  detail: (reference: string) =>
    request<Detail>(`/transactions/${encodeURIComponent(reference)}`),

  reviews: () => request<{ reviews: Review[] }>("/reviews").then((r) => r.reviews),

  openReview: (body: {
    reference: string; reason: string; answers: Record<string, string>;
    note: string; urgent: boolean;
  }) => request<{ review: Review }>("/reviews", { method: "POST", body: JSON.stringify(body) })
        .then((r) => r.review),

  exportUrl: (f: Partial<Filters>) => `/api/export.csv?${filterQuery(f)}`,

  /** CSV needs the Authorization header, so it is fetched and saved client-side. */
  async downloadCsv(f: Partial<Filters>, filename: string) {
    const response = await fetch(api.exportUrl(f), {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) throw new ApiError(response.status, "export failed");
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  },
};
