"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { clearAuth, getRefreshToken, getRole, getToken } from "@/lib/auth";
import { logout as logoutRequest, Role } from "@/lib/api";
import { Language, setLanguage as persistLanguage } from "@/lib/i18n";
import { useLanguage } from "@/lib/useLanguage";

export default function NavBar() {
  const [role, setRole] = useState<Role | null>(null);
  const [hasToken, setHasToken] = useState(false);
  const pathname = usePathname();
  const { language, t } = useLanguage();

  // Read localStorage on mount AND on every client-side route change.
  // NavBar lives in the root layout, so it mounts once for the whole app —
  // without `pathname` as a dependency, logging in on /login and getting
  // redirected to /audit wouldn't refresh this component's state, since
  // Next's client-side navigation doesn't remount it.
  useEffect(() => {
    setRole(getRole());
    setHasToken(!!getToken());
  }, [pathname]);

  async function handleLogout() {
    const token = getToken();
    const refreshToken = getRefreshToken();
    // Clear local state first — the UI should reflect "logged out"
    // immediately regardless of whether the revoke request succeeds.
    clearAuth();
    setRole(null);
    setHasToken(false);
    if (token) {
      await logoutRequest(token, refreshToken);
    }
  }

  return (
    <nav className="navbar">
      <div className="navbar-links">
        <Link href="/">{t("nav.triage")}</Link>
        <Link href="/audit">{t("nav.providerAudit")}</Link>
        <Link href="/analytics">{t("nav.analytics")}</Link>
        {role === "admin" && <Link href="/admin">{t("nav.userManagement")}</Link>}
      </div>
      <div className="navbar-auth">
        <select
          className="navbar-language-select"
          value={language}
          onChange={(e) => persistLanguage(e.target.value as Language)}
          aria-label="Language"
        >
          <option value="en">English</option>
          <option value="es">Español</option>
        </select>
        {hasToken ? (
          <>
            <span className="navbar-role">
              {t("nav.signedInAs")} {role}
            </span>
            <button onClick={handleLogout} className="navbar-logout">
              {t("nav.logOut")}
            </button>
          </>
        ) : (
          <Link href="/login">{t("nav.logIn")}</Link>
        )}
      </div>
    </nav>
  );
}
