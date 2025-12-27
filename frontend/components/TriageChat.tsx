"use client";

import { useEffect, useState } from "react";
import { fetchTriageHistory, submitIntakeText, TriageComplete } from "@/lib/api";
import { getToken } from "@/lib/auth";
import TierBadge from "@/components/TierBadge";
import PhotoGallery from "@/components/PhotoGallery";
import { useLanguage } from "@/lib/useLanguage";

interface Exchange {
  id: number;
  userText: string;
  result?: TriageComplete;
  followUpQuestion?: string;
  error?: string;
}

let nextId = 1;

export default function TriageChat() {
  const { language, t } = useLanguage();
  const [input, setInput] = useState("");
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  // Raw messages sent so far in the CURRENT, not-yet-finalized conversation
  // — sent back as prior_turns on the next message. Reset to [] whenever a
  // triage decision finalizes, so the next message starts a fresh
  // conversation instead of endlessly accumulating turns. See
  // backend/app/intake/conversation.py for how the backend merges these.
  const [conversationTurns, setConversationTurns] = useState<string[]>([]);
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const token = getToken();
    setToken(token);
    if (!token) {
      setHistoryLoaded(true);
      return;
    }
    // History is a nice-to-have, not on the critical path: if it fails to
    // load (network hiccup, expired session with no valid refresh token)
    // the chat still works fine starting from an empty transcript, so
    // failures here are swallowed rather than shown as an error.
    fetchTriageHistory(token)
      .then((entries) => {
        setExchanges(
          entries.map((e) => ({
            id: nextId++,
            userText: e.user_text,
            result: {
              status: "complete",
              tier: e.tier,
              guidance: e.guidance,
              matched_rule_id: e.matched_rule_id,
              requires_human_review: e.requires_human_review,
              sources: e.sources,
              understood_symptom_ids: e.understood_symptom_ids,
              understood_severity: e.understood_severity ?? undefined,
              understood_onset: e.understood_onset ?? undefined,
            },
          }))
        );
      })
      .catch(() => {})
      .finally(() => setHistoryLoaded(true));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const text = input.trim();
    if (!text || submitting) return;

    const id = nextId++;
    const turnsSoFar = conversationTurns;
    setExchanges((prev) => [...prev, { id, userText: text }]);
    setInput("");
    setSubmitting(true);

    try {
      const response = await submitIntakeText(text, getToken(), {
        priorTurns: turnsSoFar,
        allowFollowUp: true,
        language,
      });

      if (response.status === "need_more_info") {
        // Not a decision yet — keep the conversation going. This message
        // joins the accumulated turns so the NEXT message (the patient's
        // answer to the follow-up) is merged with everything said so far.
        setConversationTurns([...turnsSoFar, text]);
        setExchanges((prev) =>
          prev.map((ex) =>
            ex.id === id ? { ...ex, followUpQuestion: response.follow_up_question } : ex
          )
        );
      } else {
        setConversationTurns([]);
        setExchanges((prev) =>
          prev.map((ex) => (ex.id === id ? { ...ex, result: response } : ex))
        );
      }
    } catch (err) {
      // fetch() itself throws a TypeError when the request never reached a
      // server at all (network failure, backend down, CORS block) — that's
      // the one case where "is the backend running?" is actually the right
      // message. Any other Error (thrown by submitIntakeText after reading
      // a real HTTP error response) carries the backend's actual detail
      // message and should be shown as-is instead of a generic fallback.
      const message =
        err instanceof TypeError
          ? t("chat.networkError")
          : err instanceof Error
            ? err.message
            : "Something went wrong.";
      setExchanges((prev) =>
        prev.map((ex) => (ex.id === id ? { ...ex, error: message } : ex))
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="triage-chat">
      <div className="transcript">
        {historyLoaded && exchanges.length === 0 && (
          <p className="empty-hint">{t("chat.emptyHint")}</p>
        )}

        {exchanges.map((ex) => (
          <div key={ex.id} className="exchange">
            <div className="bubble user-bubble">{ex.userText}</div>

            {ex.error && <div className="bubble error-bubble">{ex.error}</div>}

            {ex.followUpQuestion && (
              <div className="bubble follow-up-bubble">{ex.followUpQuestion}</div>
            )}

            {ex.result && (
              <div className={`bubble result-bubble tier-bg-${ex.result.tier}`}>
                <TierBadge tier={ex.result.tier} />

                {ex.result.tier === "emergency" && (
                  <div className="emergency-callout">{t("chat.emergencyCallout")}</div>
                )}

                <p className="guidance-text">{ex.result.guidance}</p>

                {ex.result.understood_symptom_ids &&
                  ex.result.understood_symptom_ids.length > 0 && (
                    <div className="understood">
                      <span className="understood-label">{t("chat.understoodLabel")}</span>{" "}
                      {ex.result.understood_symptom_ids.map((s) => (
                        <span key={s} className="chip">
                          {s.replaceAll("_", " ")}
                        </span>
                      ))}
                      {ex.result.understood_severity &&
                        ex.result.understood_severity !== "unknown" && (
                          <span className="chip chip-muted">
                            {t("chat.severityLabel")}: {ex.result.understood_severity}
                          </span>
                        )}
                      {ex.result.understood_onset &&
                        ex.result.understood_onset !== "unknown" && (
                          <span className="chip chip-muted">
                            {t("chat.onsetLabel")}: {ex.result.understood_onset}
                          </span>
                        )}
                    </div>
                  )}

                {ex.result.sources.length > 0 && (
                  <div className="sources">
                    {t("chat.sourcesLabel")}: {ex.result.sources.join(", ")}
                  </div>
                )}

                {ex.result.requires_human_review && (
                  <div className="human-review-note">{t("chat.humanReviewNote")}</div>
                )}

                {token && ex.result.audit_record_id != null && (
                  <PhotoGallery
                    recordId={ex.result.audit_record_id}
                    token={token}
                    canManage={true}
                  />
                )}
              </div>
            )}

            {!ex.result && !ex.error && !ex.followUpQuestion && (
              <div className="bubble result-bubble loading-bubble">{t("chat.evaluating")}</div>
            )}
          </div>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="input-row">
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={
            conversationTurns.length > 0
              ? t("chat.inputPlaceholderFollowUp")
              : t("chat.inputPlaceholderDefault")
          }
          disabled={submitting}
        />
        <button type="submit" disabled={submitting || !input.trim()}>
          {t("chat.send")}
        </button>
      </form>
    </div>
  );
}
