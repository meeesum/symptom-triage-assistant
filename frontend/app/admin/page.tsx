"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AuthError, fetchUsers, promoteUserRole, Role, UserSummary } from "@/lib/api";
import { clearAuth, getCurrentUserId, getRole, getToken } from "@/lib/auth";

type ViewState =
  | { status: "loading" }
  | { status: "no_token" }
  | { status: "forbidden" }
  | { status: "error"; message: string }
  | { status: "ready"; users: UserSummary[] };

// "org_admin" was missing here entirely — the same leftover-from-before-
// that-role-existed gap already found and fixed in /audit and
// /analytics's page-level role gates (docs/phase9d-reporting-exports.md)
// and in the Role type itself. Found here while writing E2E coverage for
// the admin journey (docs/phase10a-e2e-test-suite.md): the backend has
// accepted org_admin promotions since docs/phase8a-organizations.md, but
// there was no way to actually assign it through this UI at all.
const ROLES: Role[] = ["patient", "provider", "org_admin", "admin"];

export default function AdminPage() {
  const router = useRouter();
  const [state, setState] = useState<ViewState>({ status: "loading" });
  const [savingId, setSavingId] = useState<number | null>(null);

  function load() {
    const token = getToken();
    const role = getRole();

    if (!token) {
      setState({ status: "no_token" });
      return;
    }
    if (role !== "admin") {
      setState({ status: "forbidden" });
      return;
    }

    fetchUsers(token)
      .then((users) => setState({ status: "ready", users }))
      .catch((err) => {
        if (err instanceof AuthError) {
          setState({ status: err.status === 403 ? "forbidden" : "no_token" });
        } else {
          setState({ status: "error", message: err instanceof Error ? err.message : "Failed to load users" });
        }
      });
  }

  useEffect(load, []);

  async function handleRoleChange(userId: number, newRole: Role) {
    const token = getToken();
    if (!token) return;
    setSavingId(userId);
    try {
      const updated = await promoteUserRole(token, userId, newRole);

      if (userId === getCurrentUserId()) {
        // Changed our own role — the local token/role are now stale (the
        // backend's role changed, but this page's own access gate and the
        // NavBar both read role from localStorage, which nothing else
        // here updates). Rather than silently keep showing the admin UI
        // under a now-inaccurate local role, force a clean re-login so
        // the app's local state actually reflects the account's new role.
        clearAuth();
        router.push("/login");
        return;
      }

      // Update just the one changed row from the response we already
      // have, instead of re-fetching the entire user list for a
      // single-row edit — the PATCH response is the new source of truth.
      setState((prev) =>
        prev.status === "ready"
          ? { status: "ready", users: prev.users.map((u) => (u.id === userId ? updated : u)) }
          : prev
      );
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : "Failed to update role",
      });
    } finally {
      setSavingId(null);
    }
  }

  return (
    <main className="page">
      <header className="page-header">
        <h1>User Management</h1>
        <p className="disclaimer">
          Admin-only. Role changes take effect the next time that user logs
          in — their current token keeps its old role claim until it
          expires or they log out. Prototype: no confirmation step, no
          audit trail of who promoted whom.
        </p>
      </header>

      {state.status === "loading" && <p>Loading…</p>}

      {state.status === "no_token" && (
        <p>
          You need to be logged in as an admin to view this. <Link href="/login">Log in</Link>
        </p>
      )}

      {state.status === "forbidden" && <p>Your account doesn't have admin access to this page.</p>}

      {state.status === "error" && <p className="auth-error">{state.message}</p>}

      {state.status === "ready" && (
        <div className="audit-table-wrap">
          <table className="audit-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Email</th>
                <th>Role</th>
              </tr>
            </thead>
            <tbody>
              {state.users.map((u) => (
                <tr key={u.id}>
                  <td>{u.id}</td>
                  <td>{u.email}</td>
                  <td>
                    <select
                      value={u.role}
                      disabled={savingId === u.id}
                      onChange={(e) => handleRoleChange(u.id, e.target.value as Role)}
                    >
                      {ROLES.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
