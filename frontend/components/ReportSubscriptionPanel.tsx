"use client";

import { useEffect, useState } from "react";
import {
  cancelReportSubscription,
  fetchReportSubscription,
  ReportFormat,
  ReportFrequency,
  ReportSubscription,
  sendReportNow,
  updateReportSubscription,
} from "@/lib/api";
import { getToken } from "@/lib/auth";

// org_admin-only self-service panel — see app/api/reports.py and
// docs/phase9d-reporting-exports.md for why this is scoped to org_admin
// rather than provider/admin: a recurring digest is meaningful for an
// org-wide view, which only org_admin has. Rendered by
// app/analytics/page.tsx only when the signed-in role is "org_admin".
export default function ReportSubscriptionPanel() {
  const [sub, setSub] = useState<ReportSubscription | null>(null);
  const [frequency, setFrequency] = useState<ReportFrequency>("weekly");
  const [format, setFormat] = useState<ReportFormat>("pdf");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) return;
    fetchReportSubscription(token).then((s) => {
      setSub(s);
      if (s.frequency) setFrequency(s.frequency);
      if (s.report_format) setFormat(s.report_format);
    });
  }, []);

  async function handleSave() {
    const token = getToken();
    if (!token) return;
    setBusy(true);
    setMessage(null);
    try {
      const updated = await updateReportSubscription(token, frequency, format);
      setSub(updated);
      setMessage("Subscription saved.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to save subscription");
    } finally {
      setBusy(false);
    }
  }

  async function handleCancel() {
    const token = getToken();
    if (!token) return;
    setBusy(true);
    setMessage(null);
    try {
      await cancelReportSubscription(token);
      setSub({ subscribed: false, frequency: null, report_format: null, last_sent_at: null });
      setMessage("Subscription cancelled.");
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to cancel subscription");
    } finally {
      setBusy(false);
    }
  }

  async function handleSendNow() {
    const token = getToken();
    if (!token) return;
    setBusy(true);
    setMessage(null);
    try {
      await sendReportNow(token);
      setMessage("Report queued for delivery.");
      const refreshed = await fetchReportSubscription(token);
      setSub(refreshed);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to send report");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="chart-card report-subscription-panel">
      <h2>Scheduled reports</h2>
      <p className="empty-hint">
        Get a recurring CSV/PDF analytics report emailed to your account.
      </p>

      <div className="report-subscription-controls">
        <label>
          Frequency
          <select
            value={frequency}
            onChange={(e) => setFrequency(e.target.value as ReportFrequency)}
          >
            <option value="daily">Daily</option>
            <option value="weekly">Weekly</option>
            <option value="monthly">Monthly</option>
          </select>
        </label>

        <label>
          Format
          <select value={format} onChange={(e) => setFormat(e.target.value as ReportFormat)}>
            <option value="pdf">PDF</option>
            <option value="csv">CSV</option>
            <option value="both">Both</option>
          </select>
        </label>

        <button type="button" onClick={handleSave} disabled={busy}>
          {sub?.subscribed ? "Update" : "Subscribe"}
        </button>

        {sub?.subscribed && (
          <>
            <button type="button" onClick={handleSendNow} disabled={busy}>
              Send now
            </button>
            <button type="button" onClick={handleCancel} disabled={busy} className="navbar-logout">
              Unsubscribe
            </button>
          </>
        )}
      </div>

      {sub?.subscribed && (
        <p className="report-subscription-status">
          Subscribed ({sub.frequency}, {sub.report_format}).{" "}
          {sub.last_sent_at
            ? `Last sent ${new Date(sub.last_sent_at).toLocaleString()}.`
            : "Not sent yet."}
        </p>
      )}

      {message && <p className="empty-hint">{message}</p>}
    </div>
  );
}
