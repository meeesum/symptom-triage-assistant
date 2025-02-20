"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AnalyticsResponse,
  AuthError,
  EscalationTier,
  exportAnalyticsPdf,
  exportAuditCsv,
  fetchAnalytics,
} from "@/lib/api";
import { getRole, getToken } from "@/lib/auth";
import ReportSubscriptionPanel from "@/components/ReportSubscriptionPanel";

type ViewState =
  | { status: "loading" }
  | { status: "no_token" }
  | { status: "forbidden" }
  | { status: "error"; message: string }
  | { status: "ready"; data: AnalyticsResponse };

const TIER_ORDER: EscalationTier[] = ["emergency", "urgent", "routine", "self_care"];
const TIER_LABELS: Record<EscalationTier, string> = {
  emergency: "Emergency",
  urgent: "Urgent",
  routine: "Routine",
  self_care: "Self-care",
};

export default function AnalyticsPage() {
  const [state, setState] = useState<ViewState>({ status: "loading" });
  const [role, setRoleState] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"csv" | "pdf" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    const role = getRole();
    setRoleState(role);

    if (!token) {
      setState({ status: "no_token" });
      return;
    }
    // Matches the backend's actual gate (require_role("provider",
    // "org_admin", "admin") — see app/api/analytics.py). This frontend
    // check used to omit "org_admin" entirely, a leftover from before
    // that role existed (docs/phase8a-organizations.md) — caught while
    // adding the scheduled-reports subscription UI below, which is
    // org_admin-only and therefore unreachable without this fix.
    if (role !== "provider" && role !== "org_admin" && role !== "admin") {
      setState({ status: "forbidden" });
      return;
    }

    fetchAnalytics(token, 30)
      .then((data) => setState({ status: "ready", data }))
      .catch((err) => {
        if (err instanceof AuthError) {
          setState({ status: err.status === 403 ? "forbidden" : "no_token" });
        } else {
          setState({
            status: "error",
            message: err instanceof Error ? err.message : "Failed to load analytics",
          });
        }
      });
  }, []);

  async function handleExport(kind: "csv" | "pdf") {
    const token = getToken();
    if (!token) return;
    setExporting(kind);
    setExportError(null);
    try {
      if (kind === "csv") {
        await exportAuditCsv(token, 30);
      } else {
        await exportAnalyticsPdf(token, 30);
      }
    } catch (err) {
      setExportError(err instanceof Error ? err.message : "Export failed");
    } finally {
      setExporting(null);
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>Provider Analytics</h1>
        <p className="disclaimer">
          Scoped to your own panel (plus anonymous triage requests) — same
          visibility as the audit trail. See docs/phase7d-provider-analytics.md.
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
        <div className="analytics-grid">
          <div className="export-row">
            <button
              type="button"
              onClick={() => handleExport("csv")}
              disabled={exporting !== null}
            >
              {exporting === "csv" ? "Exporting…" : "Export CSV"}
            </button>
            <button
              type="button"
              onClick={() => handleExport("pdf")}
              disabled={exporting !== null}
            >
              {exporting === "pdf" ? "Exporting…" : "Export PDF report"}
            </button>
            {exportError && <span className="auth-error">{exportError}</span>}
          </div>

          <StatTiles data={state.data} />
          <VolumeChart volumeByDay={state.data.volume_by_day} />
          <TierChart distribution={state.data.tier_distribution} />

          {role === "org_admin" && <ReportSubscriptionPanel />}
        </div>
      )}
    </main>
  );
}

function StatTiles({ data }: { data: AnalyticsResponse }) {
  const totalVolume = data.volume_by_day.reduce((sum, d) => sum + d.count, 0);
  const { average_hours, median_hours, count } = data.time_to_follow_up;

  return (
    <div className="stat-tiles">
      <div className="stat-tile">
        <span className="stat-value">{totalVolume}</span>
        <span className="stat-label">triages, last {data.window_days}d</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">
          {average_hours !== null ? `${average_hours}h` : "—"}
        </span>
        <span className="stat-label">avg. time to follow-up</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">
          {median_hours !== null ? `${median_hours}h` : "—"}
        </span>
        <span className="stat-label">median time to follow-up</span>
      </div>
      <div className="stat-tile">
        <span className="stat-value">{count}</span>
        <span className="stat-label">referrals followed up on</span>
      </div>
    </div>
  );
}

function VolumeChart({ volumeByDay }: { volumeByDay: AnalyticsResponse["volume_by_day"] }) {
  const width = 600;
  const height = 120;
  const max = Math.max(1, ...volumeByDay.map((d) => d.count));
  const barWidth = volumeByDay.length > 0 ? width / volumeByDay.length : 0;

  return (
    <div className="chart-card">
      <h2>Triage volume by day</h2>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Bar chart of triage volume per day"
        className="volume-chart"
      >
        {volumeByDay.map((d, i) => {
          const barHeight = (d.count / max) * (height - 4);
          return (
            <rect
              key={d.date}
              x={i * barWidth + 1}
              y={height - barHeight}
              width={Math.max(barWidth - 2, 1)}
              height={barHeight}
              className="volume-bar"
            >
              <title>{`${d.date}: ${d.count}`}</title>
            </rect>
          );
        })}
      </svg>
      {volumeByDay.length === 0 && <p className="empty-hint">No data in this window.</p>}
    </div>
  );
}

function TierChart({ distribution }: { distribution: AnalyticsResponse["tier_distribution"] }) {
  const total = TIER_ORDER.reduce((sum, tier) => sum + (distribution[tier] ?? 0), 0);

  return (
    <div className="chart-card">
      <h2>Tier distribution</h2>
      {total === 0 && <p className="empty-hint">No triages in this window.</p>}
      {total > 0 && (
        <div className="tier-bars">
          {TIER_ORDER.map((tier) => {
            const count = distribution[tier] ?? 0;
            const pct = total > 0 ? (count / total) * 100 : 0;
            return (
              <div key={tier} className="tier-bar-row">
                <span className="tier-bar-label">{TIER_LABELS[tier]}</span>
                <div className="tier-bar-track">
                  <div
                    className={`tier-bar-fill tier-fill-${tier}`}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <span className="tier-bar-count">{count}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
