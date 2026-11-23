import { en, enLimits } from "./copy.en";
import { fil, filLimits } from "./copy.fil";

export type Lang = "en" | "fil";
export type CopyKey = keyof typeof en;

export function t(lang: Lang, key: CopyKey): string {
  return (lang === "fil" ? fil : en)[key];
}

export function limits(lang: Lang): readonly string[] {
  return lang === "fil" ? filLimits : enLimits;
}

export { en, fil };
