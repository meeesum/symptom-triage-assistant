"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, registerAccount } from "@/lib/api";
import { saveAuth } from "@/lib/auth";
import { useLanguage } from "@/lib/useLanguage";

export default function LoginPage() {
  const router = useRouter();
  const { t } = useLanguage();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const result = mode === "login" ? await login(email, password) : await registerAccount(email, password);
      saveAuth(result.access_token, result.refresh_token, result.role);
      // Registration always yields a patient account now — role assignment
      // is admin-controlled (see /admin). Login can land anywhere depending
      // on the account's current role.
      router.push(result.role === "patient" ? "/" : "/audit");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>{mode === "login" ? "Log in" : "Create an account"}</h1>
        {mode === "register" && (
          <p className="disclaimer">
            New accounts are patients by default. To try the provider
            dashboard, an admin needs to promote your account from{" "}
            <a href="/admin">/admin</a> — see the repo's
            docs/phase4b-auth-rbac.md and README for how to bootstrap the
            first admin account (scripts/create_admin.py).
          </p>
        )}
      </header>

      <form onSubmit={handleSubmit} className="auth-form">
        <label>
          {t("login.emailLabel")}
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>

        <label>
          {t("login.passwordLabel")}
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            minLength={8}
            required
          />
        </label>

        {error && <p className="auth-error">{error}</p>}

        <button type="submit" disabled={submitting}>
          {mode === "login" ? t("login.logInButton") : t("login.registerButton")}
        </button>
      </form>

      <button
        className="auth-toggle"
        onClick={() => {
          setMode(mode === "login" ? "register" : "login");
          setError(null);
        }}
      >
        {mode === "login" ? "Need an account? Register" : "Already have an account? Log in"}
      </button>
    </main>
  );
}
