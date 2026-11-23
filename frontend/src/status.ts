import { t, type Lang } from "./copy";
import { ApiError } from "./api";

export function statusMessage(status: number | null, lang: Lang): string | null {
  if (status === 503) return t(lang, "down");
  if (status === 409) return t(lang, "conflict");
  return null;
}

export function errorStatus(error: unknown): number | null {
  return error instanceof ApiError ? error.status : null;
}
