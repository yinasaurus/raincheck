import { en, enLimits } from "./copy.en";
import { fil, filLimits, filScopeDraft } from "./copy.fil";

export type Lang = "en" | "fil";
export type CopyKey = keyof typeof en;

export function t(lang: Lang, key: CopyKey): string {
  return (lang === "fil" ? fil : en)[key];
}

/** Filipino scope stays unpublished until a native speaker reviews filScopeDraft. */
export const showFilipinoScope = false;

export function limits(lang: Lang): readonly string[] {
  if (lang === "fil") {
    return showFilipinoScope ? [...filLimits, filScopeDraft] : filLimits;
  }
  return enLimits;
}

export { en, fil };
