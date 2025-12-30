"use client";

import { useEffect, useState } from "react";
import { getLanguage, Language, translate } from "@/lib/i18n";

// Reads the persisted language on mount and re-renders whenever any
// component calls setLanguage() (see lib/i18n.ts's "languagechange"
// event) — without this, switching languages in NavBar wouldn't update
// TriageChat until a full page reload.
export function useLanguage() {
  const [language, setLanguageState] = useState<Language>("en");

  useEffect(() => {
    setLanguageState(getLanguage());
    function onChange(e: Event) {
      setLanguageState((e as CustomEvent<Language>).detail);
    }
    window.addEventListener("languagechange", onChange);
    return () => window.removeEventListener("languagechange", onChange);
  }, []);

  return {
    language,
    t: (key: Parameters<typeof translate>[1]) => translate(language, key),
  };
}
