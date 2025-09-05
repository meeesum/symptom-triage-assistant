"""CSV and PDF report generation off the provider analytics dashboard —
see docs/phase9d-reporting-exports.md.

Two distinct exports, deliberately not the same data reshaped two ways:

  - CSV (`build_audit_csv`): the underlying RAW audit records (one row
    per triage decision) — what a provider/analyst would actually pull
    into a spreadsheet for their own analysis. Same panel-based
    visibility as GET /audit/recent, reused directly.
  - PDF (`build_analytics_pdf`): a formatted, shareable SUMMARY document
    — the exact aggregates already shown on /analytics (volume by day,
    tier distribution, follow-up stats), laid out as a report rather than
    a live dashboard. Reuses app/services/analytics.py's aggregation
    functions directly rather than re-deriving them, so the PDF can never
    drift from what the dashboard itself shows for the same window.

Both take (role, user_id, org_id) and apply the SAME visibility rule as
everywhere else in this codebase (app/services/audit_visibility.py) — an
export is not a way around panel/org scoping, it's the same scoped data
in a different shape.
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import select

from app.core.db import get_session
from app.models.audit import TriageAuditRecord
from app.services.analytics import (
    DEFAULT_WINDOW_DAYS,
    tier_distribution,
    time_to_follow_up_stats,
    triage_volume_by_day,
)
from app.services.audit_visibility import audit_visibility_clause

_CSV_COLUMNS = (
    "id",
    "created_at",
    "tier",
    "symptom_ids",
    "severity",
    "onset",
    "matched_rule_id",
    "requires_human_review",
    "decision_source",
)


def build_audit_csv(
    role: str, user_id: int, org_id: int | None = None, days: int = DEFAULT_WINDOW_DAYS
) -> bytes:
    since = datetime.now(UTC) - timedelta(days=days)
    with get_session() as session:
        query = (
            select(TriageAuditRecord)
            .where(TriageAuditRecord.created_at >= since)
            .order_by(TriageAuditRecord.id.desc())
        )
        visibility = audit_visibility_clause(role, user_id, org_id)
        if visibility is not None:
            query = query.where(visibility)
        rows = session.execute(query).scalars().all()

        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(_CSV_COLUMNS)
        for r in rows:
            writer.writerow(
                [
                    r.id,
                    r.created_at.isoformat() if r.created_at else "",
                    r.tier,
                    ";".join(r.symptom_ids),
                    r.severity,
                    r.onset,
                    r.matched_rule_id or "",
                    r.requires_human_review,
                    r.decision_source,
                ]
            )
        return buf.getvalue().encode("utf-8")


def build_analytics_pdf(
    role: str, user_id: int, org_id: int | None = None, days: int = DEFAULT_WINDOW_DAYS
) -> bytes:
    volume = triage_volume_by_day(role, user_id, days, org_id)
    tiers = tier_distribution(role, user_id, days, org_id)
    follow_up = time_to_follow_up_stats(role, user_id, days, org_id)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=letter, title="Triage Analytics Report")
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Symptom Triage Assistant — Analytics Report", styles["Title"]),
        Paragraph(
            f"Window: last {days} days, generated "
            f"{datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
            styles["Normal"],
        ),
        Paragraph(
            "Informational only — not a diagnostic tool. This report reflects only "
            "the records visible to the recipient's own role/panel/organization.",
            styles["Italic"],
        ),
        Spacer(1, 0.3 * inch),
        Paragraph("Tier distribution", styles["Heading2"]),
        _dict_table([("Tier", "Count"), *tiers.items()]),
        Spacer(1, 0.25 * inch),
        Paragraph("Time to first follow-up", styles["Heading2"]),
        _dict_table(
            [
                ("Metric", "Value"),
                ("Average hours", _or_na(follow_up["average_hours"])),
                ("Median hours", _or_na(follow_up["median_hours"])),
                ("Referrals counted", follow_up["count"]),
            ]
        ),
        Spacer(1, 0.25 * inch),
        Paragraph("Daily triage volume", styles["Heading2"]),
        _dict_table([("Date", "Count"), *[(d["date"], d["count"]) for d in volume]]),
    ]
    doc.build(story)
    return buf.getvalue()


def _or_na(value: float | None) -> str | float:
    return value if value is not None else "n/a"


def _dict_table(rows: list[tuple]) -> Table:
    table = Table([[str(a), str(b)] for a, b in rows], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563eb")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
            ]
        )
    )
    return table
