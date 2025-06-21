"use client";

import { EscalationTier } from "@/lib/api";
import { useLanguage } from "@/lib/useLanguage";

const TIER_KEY: Record<EscalationTier, "tier.emergency" | "tier.urgent" | "tier.routine" | "tier.self_care"> = {
  emergency: "tier.emergency",
  urgent: "tier.urgent",
  routine: "tier.routine",
  self_care: "tier.self_care",
};

export default function TierBadge({ tier }: { tier: EscalationTier }) {
  const { t } = useLanguage();
  return (
    <span className={`tier-badge tier-${tier}`}>
      {t(TIER_KEY[tier])}
    </span>
  );
}
