// Client-side auth state. Deliberately minimal — localStorage, no
// server-side session. Matches the backend's own prototype-grade auth
// (see backend/docs/phase4b-auth-rbac.md): fine for demonstrating the
// login -> role-gated-page flow end to end, not a production session
// story (XSS could read these tokens; a real deployment would want an
// httpOnly cookie instead of localStorage).
//
// The backend issues a short-lived (1h) access token plus a long-lived
// (7d) refresh token — both are stored here, and logout revokes both
// (see lib/api.ts's logout()). authFetch() in lib/api.ts now retries once
// via refreshAccessToken() on a 401, so a session survives past the 1h
// access-token expiry as long as the refresh token (7d) is still valid —
// see that file for the retry logic. What's still NOT built: this only
// covers requests made through authFetch (fetchUsers, promoteUserRole,
// fetchRecentAuditRecords); there's no global interceptor, and no
// proactive refresh before expiry (it only kicks in reactively, on the
// first 401 a stale token produces).

import type { Role } from "@/lib/api";

const TOKEN_KEY = "triage_auth_token";
const REFRESH_TOKEN_KEY = "triage_auth_refresh_token";
const ROLE_KEY = "triage_auth_role";

export function saveAuth(token: string, refreshToken: string, role: Role) {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  localStorage.setItem(ROLE_KEY, role);
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function getRole(): Role | null {
  return localStorage.getItem(ROLE_KEY) as Role | null;
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
}

// Decodes the access token's payload WITHOUT verifying its signature —
// that's fine here, since this is only used for a UX check (did the admin
// just change their OWN role?), never for authorization. Real
// authorization always happens server-side against the verified token.
export function getCurrentUserId(): number | null {
  const token = getToken();
  if (!token) return null;
  try {
    const payloadB64 = token.split(".")[1];
    const payload = JSON.parse(atob(payloadB64));
    return Number(payload.sub);
  } catch {
    return null;
  }
}
