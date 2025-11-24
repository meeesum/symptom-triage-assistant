import type { Metadata, Viewport } from "next";
import "./globals.css";
import NavBar from "@/components/NavBar";
import ServiceWorkerRegister from "@/components/ServiceWorkerRegister";

export const metadata: Metadata = {
  title: "Symptom Triage Assistant (prototype)",
  description: "Informational symptom triage — not a diagnostic tool.",
  manifest: "/manifest.json",
  icons: {
    icon: [
      { url: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: "/icons/apple-touch-icon.png",
  },
};

// theme_color is duplicated here (matching manifest.json's) because iOS
// Safari reads the <meta name="theme-color"> tag Next generates from
// this, not the manifest, for the status-bar tint — the manifest alone
// covers Android/desktop install.
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#2563eb",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>
        <ServiceWorkerRegister />
        <NavBar />
        {children}
      </body>
    </html>
  );
}
