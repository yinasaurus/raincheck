import { t, type Lang } from "./copy";

export interface PayRow {
  month: number;
  payment_cents: number;
  note?: string;
}

const REDUCED = /reduced\s+([0-9.]+)%/i;

export function strictlyBelow(millimetres: number, line: number): boolean {
  return millimetres < line;
}

export function formatMm(value: number): string {
  return `${value.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} mm`;
}

export function formatPercent(probability: number): string {
  return `${Math.round(probability * 100)}%`;
}

export function formatAmount(cents: number): string {
  return (cents / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function showMm(value: unknown, lang: Lang): string {
  return isNumber(value) ? formatMm(value) : t(lang, "na");
}

export function showChance(value: unknown, lang: Lang): string {
  return isNumber(value) ? formatPercent(value) : t(lang, "na");
}

/** Farmer copy keeps the API sentence and drops a raw four-decimal probability. */
export function withoutRawProbability(text: string): string {
  const kept = text
    .split(/(?<=\.)\s+/)
    .filter((sentence) => !/\d\.\d{4}/.test(sentence))
    .join(" ")
    .replace(/\b\d+\.\d{4}\b/g, "")
    .replace(/\s{2,}/g, " ")
    .trim();
  return kept;
}

export function showAmount(cents: unknown, lang: Lang): string {
  return isNumber(cents) ? formatAmount(cents) : t(lang, "na");
}

export function normalToDate(cumulative: unknown, fractionOfNormal: unknown): number | null {
  if (!isNumber(cumulative) || !isNumber(fractionOfNormal) || fractionOfNormal <= 0) return null;
  return cumulative / fractionOfNormal;
}

export function firstChanged(before: PayRow[], after: PayRow[]): { month: number; before: number; after: number } | null {
  const byMonth = new Map(after.map((row) => [row.month, row.payment_cents]));
  for (const row of before) {
    const next = byMonth.get(row.month);
    if (next !== undefined && next !== row.payment_cents) {
      return { month: row.month, before: row.payment_cents, after: next };
    }
  }
  return null;
}

export function reducedWindow(after: PayRow[]): { count: number; percent: number | null } {
  const hits = after.map((row) => row.note?.match(REDUCED)).filter((match) => match != null);
  const percent = hits[0] ? Number(hits[0][1]) : null;
  return { count: hits.length, percent: Number.isFinite(percent) ? percent : null };
}

export function reliefSentence(lang: Lang, count: number, percent: number): string {
  if (lang === "fil") {
    return `Ang susunod na ${count} bayad ay ${percent}% na mas mababa.`;
  }
  return `Your next ${count} payments are ${percent}% lower.`;
}

export const BANNED_WORDS = /\b(transactions?|hashes?|contracts?|oracles?|blockchain|wallets?|gas|ethereum)\b/i;
