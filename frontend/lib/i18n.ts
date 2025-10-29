// Minimal i18n: a language preference persisted in localStorage (same
// pattern as lib/auth.ts) plus a flat translation dictionary. No ICU
// pluralization/formatting library — this app's strings are simple enough
// that it isn't worth the dependency yet.
//
// Scope (see backend/docs/phase9b-internationalization.md for the fuller
// picture): only the PATIENT-facing surface is translated here — the
// triage chat, tier badges, and the login form. The provider/admin pages
// (audit, analytics, user management) are English-only; those are
// internal tools used by clinical/operations staff, not the safety-
// critical patient path the roadmap's i18n epic is actually about.
//
// Language changes are broadcast via a "languagechange" window event so
// every mounted component using useLanguage() re-renders together instead
// of only the one that changed localStorage (NavBar's switcher and
// TriageChat both need to react to the same change).

export type Language = "en" | "es";

const LANGUAGE_KEY = "triage_language";
export const SUPPORTED_LANGUAGES: Language[] = ["en", "es"];
const DEFAULT_LANGUAGE: Language = "en";

export function getLanguage(): Language {
  if (typeof window === "undefined") return DEFAULT_LANGUAGE;
  const stored = localStorage.getItem(LANGUAGE_KEY);
  return stored === "es" ? "es" : DEFAULT_LANGUAGE;
}

export function setLanguage(language: Language) {
  localStorage.setItem(LANGUAGE_KEY, language);
  window.dispatchEvent(new CustomEvent("languagechange", { detail: language }));
}

type TranslationKey =
  | "nav.triage"
  | "nav.providerAudit"
  | "nav.analytics"
  | "nav.userManagement"
  | "nav.signedInAs"
  | "nav.logOut"
  | "nav.logIn"
  | "chat.emptyHint"
  | "chat.inputPlaceholderFollowUp"
  | "chat.inputPlaceholderDefault"
  | "chat.send"
  | "chat.evaluating"
  | "chat.understoodLabel"
  | "chat.severityLabel"
  | "chat.onsetLabel"
  | "chat.sourcesLabel"
  | "chat.humanReviewNote"
  | "chat.emergencyCallout"
  | "chat.networkError"
  | "tier.emergency"
  | "tier.urgent"
  | "tier.routine"
  | "tier.self_care"
  | "login.emailLabel"
  | "login.passwordLabel"
  | "login.logInButton"
  | "login.registerButton"
  | "login.disclaimer";

const TRANSLATIONS: Record<Language, Record<TranslationKey, string>> = {
  en: {
    "nav.triage": "Triage",
    "nav.providerAudit": "Provider Audit",
    "nav.analytics": "Analytics",
    "nav.userManagement": "User Management",
    "nav.signedInAs": "signed in as",
    "nav.logOut": "Log out",
    "nav.logIn": "Log in",
    "chat.emptyHint":
      "Describe what you're experiencing in your own words — for example " +
      "\"I have a mild cough and sore throat\" or \"sudden chest pain and " +
      "sweating\". This is a prototype; do not use it for real medical decisions.",
    "chat.inputPlaceholderFollowUp": "Answer the question above…",
    "chat.inputPlaceholderDefault": "Describe your symptoms…",
    "chat.send": "Send",
    "chat.evaluating": "Evaluating…",
    "chat.understoodLabel": "Understood:",
    "chat.severityLabel": "severity",
    "chat.onsetLabel": "onset",
    "chat.sourcesLabel": "Sources",
    "chat.humanReviewNote": "This response has been flagged for human review.",
    "chat.emergencyCallout":
      "If this is a medical emergency, call 911 (or your local emergency number) now.",
    "chat.networkError": "Couldn't reach the triage service. Is the backend running?",
    "tier.emergency": "Emergency — call 911 now",
    "tier.urgent": "Urgent — seek care today",
    "tier.routine": "Routine — schedule a visit",
    "tier.self_care": "Self-care",
    "login.emailLabel": "Email",
    "login.passwordLabel": "Password",
    "login.logInButton": "Log in",
    "login.registerButton": "Register",
    "login.disclaimer": "This is a prototype account system.",
  },
  es: {
    "nav.triage": "Triaje",
    "nav.providerAudit": "Auditoría de Proveedores",
    "nav.analytics": "Analítica",
    "nav.userManagement": "Gestión de Usuarios",
    "nav.signedInAs": "sesión iniciada como",
    "nav.logOut": "Cerrar sesión",
    "nav.logIn": "Iniciar sesión",
    "chat.emptyHint":
      "Describe lo que estás sintiendo con tus propias palabras — por ejemplo " +
      "\"tengo una tos leve y dolor de garganta\" o \"dolor de pecho repentino y " +
      "sudoración\". Esto es un prototipo; no lo uses para decisiones médicas reales.",
    "chat.inputPlaceholderFollowUp": "Responde la pregunta de arriba…",
    "chat.inputPlaceholderDefault": "Describe tus síntomas…",
    "chat.send": "Enviar",
    "chat.evaluating": "Evaluando…",
    "chat.understoodLabel": "Entendido:",
    "chat.severityLabel": "severidad",
    "chat.onsetLabel": "inicio",
    "chat.sourcesLabel": "Fuentes",
    "chat.humanReviewNote": "Esta respuesta ha sido marcada para revisión humana.",
    "chat.emergencyCallout":
      "Si esto es una emergencia médica, llama al 911 (o a tu número de emergencia local) ahora.",
    "chat.networkError":
      "No se pudo conectar con el servicio de triaje. ¿Está el backend en ejecución?",
    "tier.emergency": "Emergencia — llama al 911 ahora",
    "tier.urgent": "Urgente — busca atención hoy",
    "tier.routine": "Rutinario — agenda una visita",
    "tier.self_care": "Autocuidado",
    "login.emailLabel": "Correo electrónico",
    "login.passwordLabel": "Contraseña",
    "login.logInButton": "Iniciar sesión",
    "login.registerButton": "Registrarse",
    "login.disclaimer": "Este es un sistema de cuentas de prototipo.",
  },
};

export function translate(language: Language, key: TranslationKey): string {
  return TRANSLATIONS[language][key];
}
