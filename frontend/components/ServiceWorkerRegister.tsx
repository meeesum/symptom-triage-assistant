"use client";

import { useEffect } from "react";

// Registers public/sw.js — a client component because service worker
// registration is a browser-only API with no server-render equivalent.
// See public/sw.js for what it actually does (and deliberately doesn't).
export default function ServiceWorkerRegister() {
  useEffect(() => {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        // Registration failing (unsupported browser, blocked by an
        // extension, etc.) shouldn't break the app — the PWA/offline
        // shell is a nice-to-have layered on top of a site that already
        // works fully without it.
      });
    }
  }, []);

  return null;
}
