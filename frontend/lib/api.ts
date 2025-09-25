// Thin client for the FastAPI backend. Mirrors the response contract
// returned by backend/app/api/triage.py — keep these in sync manually for
// now; codegen (openapi-typescript) is a reasonable Phase-6 upgrade once
// the contract stabilizes.

import { clearAuth, getRefreshToken, saveAuth } from "@/lib/auth";
import type { Language } from "@/lib/i18n";

export type EscalationTier = "emergency" | "urgent" | "routine" | "self_care";

// A completed triage decision. `status` is always "complete" here — kept
// on the type (rather than a bare TriageResult with no status field) so
// this and TriageFollowUp form a discriminated union callers can switch
// on, matching what /triage/intake actually returns since the multi-turn
// epic — see backend/docs/phase6c-multi-turn-triage.md.
export interface TriageComplete {
  status: "complete";
  tier: EscalationTier;
  guidance: string;
  matched_rule_id: string | null;
  requires_human_review: boolean;
  sources: string[];
  understood_symptom_ids?: string[];
  understood_severity?: string;
  understood_onset?: string;
  // The audit-trail record this decision was logged as — null only if
  // the DB write itself failed (see backend/app/services/audit_log.py;
  // the stdout log is still the record of what happened in that case).
  // Present so the frontend can attach a symptom photo to this specific
  // triage decision — see components/PhotoGallery.tsx.
  audit_record_id?: number | null;
}

// Not a decision — the backend needs more information first (see
// app/intake/conversation.py's confidence check). Never returned for an
// emergency/urgent tier; the safety fast path always finalizes instead.
export interface TriageFollowUp {
  status: "need_more_info";
  follow_up_question: string;
  understood_symptom_ids: string[];
  understood_severity: string;
  understood_onset: string;
}

export type TriageResult = TriageComplete;
export type IntakeResponse = TriageComplete | TriageFollowUp;

// "org_admin" (per-org superuser — see backend/app/models/user.py) was
// missing here entirely — a leftover from before that role existed
// (docs/phase8a-organizations.md). Caught by TypeScript itself once
// audit/page.tsx and analytics/page.tsx were fixed to actually check for
// it: comparing a Role against "org_admin" was a compile error because
// the type system had no idea the role existed.
export type Role = "patient" | "provider" | "org_admin" | "admin";

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  role: Role;
}

export interface AuditRecord {
  id: number;
  created_at: string | null;
  symptom_ids: string[];
  severity: string;
  onset: string;
  tier: EscalationTier;
  matched_rule_id: string | null;
  requires_human_review: boolean;
  decision_source: string;
}

export interface VolumeDay {
  date: string;
  count: number;
}

export interface FollowUpStats {
  average_hours: number | null;
  median_hours: number | null;
  count: number;
}

export interface AnalyticsResponse {
  window_days: number;
  volume_by_day: VolumeDay[];
  tier_distribution: Record<EscalationTier, number>;
  time_to_follow_up: FollowUpStats;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

// Thrown for 401/403 specifically so callers (the audit page) can tell
// "you're not logged in" apart from "the request itself failed" and show
// the right message instead of a generic error.
export class AuthError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function throwForErrorResponse(res: Response): Promise<never> {
  const body = await res.json().catch(() => ({}));
  if (res.status === 401 || res.status === 403) {
    throw new AuthError(res.status, body.detail ?? "not authorized");
  }
  throw new Error(body.detail ?? `Request failed: ${res.status}`);
}

// Attempts one silent refresh using the stored refresh token. Returns the
// new access token on success, or null if there's no refresh token or the
// refresh itself failed (expired/revoked/reused) — in which case local
// auth state is cleared, since a dead refresh token means the session is
// genuinely over, not just the access token.
//
// Single-flight by design: refresh tokens rotate on every use (see
// backend/app/services/refresh_tokens.py), so if two authFetch calls hit
// a 401 around the same time (React StrictMode's dev-mode double-effect
// reproduces this reliably, but any two genuinely concurrent authenticated
// requests after expiry would too) and each independently called
// refreshAccessToken(), the loser would present the SAME refresh token
// the winner just consumed — the backend's reuse detection would reject
// it, and the loser's catch block would clearAuth(), wiping out the
// winner's freshly-saved tokens moments after they were written. Caught
// live: the page rendered successfully but localStorage came back empty
// right after. `inFlightRefresh` makes every concurrent caller await the
// SAME network call instead of racing separate ones.
let inFlightRefresh: Promise<string | null> | null = null;

async function trySilentRefresh(): Promise<string | null> {
  if (inFlightRefresh) return inFlightRefresh;

  inFlightRefresh = (async () => {
    const refreshToken = getRefreshToken();
    if (!refreshToken) return null;
    try {
      const result = await refreshAccessToken(refreshToken);
      saveAuth(result.access_token, result.refresh_token, result.role);
      return result.access_token;
    } catch {
      clearAuth();
      return null;
    }
  })();

  try {
    return await inFlightRefresh;
  } finally {
    inFlightRefresh = null;
  }
}

// Shared bearer-token fetch + error handling, extracted from three
// near-identical copies of this logic (fetchUsers, promoteUserRole,
// fetchRecentAuditRecords each repeated the Authorization header
// construction and the 401/403-vs-other-error branching). Any future
// authenticated endpoint should go through this rather than re-copying
// the pattern.
//
// On a 401 specifically (not 403 — a valid-but-wrong-role token refreshing
// won't fix a 403), it now retries ONCE after a silent token refresh: the
// access token is short-lived (1h) by design, and without this the whole
// point of having a refresh token was undermined — every session would
// still just die after an hour, same as before refresh tokens existed.
async function authFetch(url: string, token: string, init: RequestInit = {}): Promise<Response> {
  const res = await fetch(url, {
    ...init,
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${token}` },
  });

  if (res.status !== 401) {
    if (!res.ok) return throwForErrorResponse(res);
    return res;
  }

  const newToken = await trySilentRefresh();
  if (!newToken) return throwForErrorResponse(res); // no refresh token, or refresh itself failed

  const retryRes = await fetch(url, {
    ...init,
    headers: { ...(init.headers ?? {}), Authorization: `Bearer ${newToken}` },
  });
  if (!retryRes.ok) return throwForErrorResponse(retryRes);
  return retryRes;
}

export interface ChatHistoryEntry {
  id: number;
  created_at: string | null;
  user_text: string;
  tier: EscalationTier;
  guidance: string;
  matched_rule_id: string | null;
  requires_human_review: boolean;
  sources: string[];
  understood_symptom_ids: string[];
  understood_severity: string | null;
  understood_onset: string | null;
}

export async function submitIntakeText(
  text: string,
  token: string | null,
  options?: { priorTurns?: string[]; allowFollowUp?: boolean; language?: Language }
): Promise<IntakeResponse> {
  // Works with or without a token — /triage/intake never requires login.
  // When a token IS present, the backend also saves the exchange to that
  // patient's chat history (see /triage/history) — purely a side effect
  // on the backend; this call's behavior/response shape is unaffected
  // either way, so no retry-on-401 here (an expired token just means this
  // one exchange doesn't get saved, not that the request should fail).
  //
  // priorTurns/allowFollowUp opt into multi-turn triage (see
  // backend/app/intake/conversation.py) — omitted, the backend behaves
  // exactly as it always has: one message in, one final decision out.
  // `language` defaults to "en" server-side when omitted (see
  // backend/app/api/triage.py's IntakeRequest).
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}/triage/intake`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      text,
      prior_turns: options?.priorTurns ?? [],
      allow_follow_up: options?.allowFollowUp ?? false,
      language: options?.language ?? "en",
    }),
  });

  if (!res.ok) {
    // Read the response body's `detail` field (FastAPI's error shape),
    // same as handleAuthResponse below — a bare status/statusText string
    // used to be thrown here instead, which meant a real backend error
    // (e.g. a 422 validation message) was discarded and TriageChat showed
    // a generic "is the backend running?" message even when it was.
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Triage request failed: ${res.status} ${res.statusText}`);
  }

  return res.json();
}

export async function fetchTriageHistory(token: string, limit = 50): Promise<ChatHistoryEntry[]> {
  const res = await authFetch(`${API_BASE}/triage/history?limit=${limit}`, token);
  return res.json();
}

async function handleAuthResponse(res: Response): Promise<AuthResponse> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed: ${res.status}`);
  }
  return res.json();
}

export async function registerAccount(email: string, password: string): Promise<AuthResponse> {
  // No `role` field — registration always creates a patient account now.
  // See backend/docs/phase4b-auth-rbac.md: role assignment is
  // admin-controlled via promoteUserRole(), not self-service at signup.
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return handleAuthResponse(res);
}

export interface UserSummary {
  id: number;
  email: string;
  role: Role;
}

export async function fetchUsers(token: string): Promise<UserSummary[]> {
  const res = await authFetch(`${API_BASE}/admin/users`, token);
  return res.json();
}

export async function promoteUserRole(
  token: string,
  userId: number,
  role: Role
): Promise<UserSummary> {
  const res = await authFetch(`${API_BASE}/admin/users/${userId}/role`, token, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  return res.json();
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  return handleAuthResponse(res);
}

export async function logout(accessToken: string, refreshToken: string | null): Promise<void> {
  // Best-effort: the caller (NavBar) clears local auth state regardless of
  // whether this network call succeeds, since staying "logged in" in the
  // UI just because the revoke request failed would be worse than a token
  // that's technically still valid server-side for a bit longer.
  // Includes the refresh token (when we have one) so logout revokes BOTH
  // — otherwise the refresh token would keep working and could mint a
  // fresh access token even after "logging out".
  await fetch(`${API_BASE}/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
    body: JSON.stringify({ refresh_token: refreshToken }),
  }).catch(() => {});
}

export async function refreshAccessToken(refreshToken: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new AuthError(res.status, body.detail ?? "refresh failed");
  }
  return res.json();
}

export async function fetchRecentAuditRecords(
  token: string,
  limit = 50
): Promise<AuditRecord[]> {
  const res = await authFetch(`${API_BASE}/audit/recent?limit=${limit}`, token);
  return res.json();
}

export async function fetchAnalytics(token: string, days = 30): Promise<AnalyticsResponse> {
  const res = await authFetch(`${API_BASE}/audit/analytics?days=${days}`, token);
  return res.json();
}

// Symptom photo upload — see backend/app/api/symptom_photos.py and
// docs/phase9c-symptom-photo-upload.md. Deliberately no image analysis
// anywhere in this client: upload, list, view, delete only.

export interface SymptomPhoto {
  id: number;
  audit_record_id: number;
  content_type: string;
  size_bytes: number;
  created_at: string | null;
}

export async function uploadSymptomPhoto(
  token: string,
  recordId: number,
  file: File
): Promise<SymptomPhoto> {
  const formData = new FormData();
  formData.append("file", file);
  // Not routed through authFetch(): that helper sets a JSON
  // Content-Type header unconditionally, which would override the
  // multipart boundary the browser sets automatically for FormData.
  const res = await fetch(`${API_BASE}/audit/${recordId}/photos`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `Photo upload failed: ${res.status}`);
  }
  return res.json();
}

export async function listSymptomPhotos(token: string, recordId: number): Promise<SymptomPhoto[]> {
  const res = await authFetch(`${API_BASE}/audit/${recordId}/photos`, token);
  return res.json();
}

// Returns a blob: object URL for use as an <img src> — plain <img
// src="..."> can't send an Authorization header, so the image bytes are
// fetched authenticated first and handed to the browser as a local blob
// URL instead. Callers must URL.revokeObjectURL() it when done (see
// PhotoGallery.tsx's cleanup) or the blob leaks for the tab's lifetime.
export async function fetchSymptomPhotoBlobUrl(
  token: string,
  recordId: number,
  photoId: number
): Promise<string> {
  const res = await authFetch(`${API_BASE}/audit/${recordId}/photos/${photoId}`, token);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export async function deleteSymptomPhoto(
  token: string,
  recordId: number,
  photoId: number
): Promise<void> {
  await authFetch(`${API_BASE}/audit/${recordId}/photos/${photoId}`, token, {
    method: "DELETE",
  });
}

// Reporting exports — see backend/app/api/reports.py and
// docs/phase9d-reporting-exports.md.

// Fetches the export authenticated, then triggers a browser download via
// a throwaway blob: URL + a synthetic <a click> — a plain <a href> can't
// send an Authorization header, same reason lib/api.ts's photo fetch
// works this way (see fetchSymptomPhotoBlobUrl above).
async function downloadAuthenticated(url: string, token: string, filename: string): Promise<void> {
  const res = await authFetch(url, token);
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(objectUrl);
}

export async function exportAuditCsv(token: string, days = 30): Promise<void> {
  await downloadAuthenticated(
    `${API_BASE}/audit/export.csv?days=${days}`,
    token,
    "triage_audit_export.csv"
  );
}

export async function exportAnalyticsPdf(token: string, days = 30): Promise<void> {
  await downloadAuthenticated(
    `${API_BASE}/audit/analytics/export.pdf?days=${days}`,
    token,
    "triage_analytics_report.pdf"
  );
}

export type ReportFrequency = "daily" | "weekly" | "monthly";
export type ReportFormat = "csv" | "pdf" | "both";

export interface ReportSubscription {
  subscribed: boolean;
  frequency: ReportFrequency | null;
  report_format: ReportFormat | null;
  last_sent_at: string | null;
}

export async function fetchReportSubscription(token: string): Promise<ReportSubscription> {
  const res = await authFetch(`${API_BASE}/reports/subscription`, token);
  return res.json();
}

export async function updateReportSubscription(
  token: string,
  frequency: ReportFrequency,
  reportFormat: ReportFormat
): Promise<ReportSubscription> {
  const res = await authFetch(`${API_BASE}/reports/subscription`, token, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ frequency, report_format: reportFormat }),
  });
  return res.json();
}

export async function cancelReportSubscription(token: string): Promise<void> {
  await authFetch(`${API_BASE}/reports/subscription`, token, { method: "DELETE" });
}

export async function sendReportNow(token: string): Promise<void> {
  await authFetch(`${API_BASE}/reports/subscription/send-now`, token, { method: "POST" });
}
