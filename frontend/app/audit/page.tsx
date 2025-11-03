"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { AuditRecord, AuthError, fetchRecentAuditRecords } from "@/lib/api";
import { getRole, getToken } from "@/lib/auth";
import TierBadge from "@/components/TierBadge";
import PhotoGallery from "@/components/PhotoGallery";

type ViewState =
  | { status: "loading" }
  | { status: "no_token" }
  | { status: "forbidden" }
  | { status: "error"; message: string }
  | { status: "ready"; records: AuditRecord[] };

export default function AuditPage() {
  const [state, setState] = useState<ViewState>({ status: "loading" });
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    const role = getRole();
    setToken(token);

    if (!token) {
      setState({ status: "no_token" });
      return;
    }
    // Matches the backend's actual gate (require_role("provider",
    // "org_admin", "admin") — see app/api/audit.py). Same pre-existing
    // frontend gap as analytics/page.tsx — fixed alongside it.
    if (role !== "provider" && role !== "org_admin" && role !== "admin") {
      setState({ status: "forbidden" });
      return;
    }

    fetchRecentAuditRecords(token, 50)
      .then((records) => setState({ status: "ready", records }))
      .catch((err) => {
        if (err instanceof AuthError) {
          setState({ status: err.status === 403 ? "forbidden" : "no_token" });
        } else {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "Failed to load audit records",
          });
        }
      });
  }, []);

  return (
    <main className="page">
      <header className="page-header">
        <h1>Provider Audit Trail</h1>
        <p className="disclaimer">
          Scoped to your own patient panel, plus anonymous triage requests
          (not tied to any specific patient) — an admin sees every record.
          See docs/phase7a-patient-panels.md.
        </p>
      </header>

      {state.status === "loading" && <p>Loading…</p>}

      {state.status === "no_token" && (
        <p>
          You need to be logged in as a provider or admin to view this.{" "}
          <Link href="/login">Log in</Link>
        </p>
      )}

      {state.status === "forbidden" && (
        <p>Your account doesn't have provider/admin access to this page.</p>
      )}

      {state.status === "error" && <p className="auth-error">{state.message}</p>}

      {state.status === "ready" && (
        <div className="audit-table-wrap">
          <table className="audit-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Tier</th>
                <th>Symptoms</th>
                <th>Severity</th>
                <th>Onset</th>
                <th>Rule</th>
                <th>Review?</th>
                <th>Source</th>
                <th>Photos</th>
              </tr>
            </thead>
            <tbody>
              {state.records.map((r) => (
                <tr key={r.id}>
                  <td>{r.created_at ? new Date(r.created_at).toLocaleString() : "—"}</td>
                  <td>
                    <TierBadge tier={r.tier} />
                  </td>
                  <td>{r.symptom_ids.join(", ") || "—"}</td>
                  <td>{r.severity}</td>
                  <td>{r.onset}</td>
                  <td>{r.matched_rule_id ?? "—"}</td>
                  <td>{r.requires_human_review ? "yes" : "no"}</td>
                  <td>{r.decision_source}</td>
                  <td>
                    {token && <PhotoGallery recordId={r.id} token={token} canManage={false} />}
                  </td>
                </tr>
              ))}
              {state.records.length === 0 && (
                <tr>
                  <td colSpan={9}>No audit records yet.</td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
