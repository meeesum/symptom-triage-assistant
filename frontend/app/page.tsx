import TriageChat from "@/components/TriageChat";

export default function Home() {
  return (
    <main className="page">
      <header className="page-header">
        <h1>Symptom Triage Assistant</h1>
        <p className="disclaimer">
          Prototype — informational only, not a diagnostic tool. Always
          contact a healthcare provider for medical concerns, and call
          emergency services for anything life-threatening.
        </p>
      </header>

      <TriageChat />
    </main>
  );
}
