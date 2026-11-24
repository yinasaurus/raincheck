import type { BacktestBody, DemoRun, DemoYear, EvidenceCheck, RegionBody, RiskBody, SchedulePreview, WeekRow } from "./types";

const BASE = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(503, "The record service is not running");
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* The status line is enough when the body is not JSON. */
    }
    throw new ApiError(response.status, detail || "Request failed");
  }
  return (await response.json()) as T;
}

function dropDeprecatedWeek(week: WeekRow & { risk_score?: unknown; baseline_score?: unknown }): WeekRow {
  const { risk_score: _risk, baseline_score: _base, ...rest } = week;
  void _risk;
  void _base;
  return rest;
}

export function getDemoYears(): Promise<{ years: DemoYear[] }> {
  return request("/api/demo/years");
}

export function getRegion(): Promise<RegionBody> {
  return request("/api/region");
}

export function getBacktest(): Promise<BacktestBody> {
  return request("/api/backtest");
}

export async function getRisk(): Promise<RiskBody> {
  const body = await request<RiskBody & { risk_score?: unknown; baseline_score?: unknown }>("/api/risk");
  const { risk_score: _risk, baseline_score: _base, ...rest } = body;
  void _risk;
  void _base;
  return rest;
}

export async function runDemo(year: number): Promise<DemoRun> {
  const body = await request<DemoRun & { model_score?: unknown; rule_score?: unknown; weekly: WeekRow[] }>(
    "/api/demo/run",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ year }),
    },
  );
  // The top-level rule_score on this route is the old baseline, not the payment-line rule.
  const { model_score: _model, rule_score: _topRule, weekly, ...rest } = body;
  void _model;
  void _topRule;
  return { ...rest, weekly: (weekly ?? []).map(dropDeprecatedWeek) };
}

export function previewSchedule(query: {
  principal_cents: number;
  rate_bps: number;
  term: number;
  kind: "REDUCTION" | "DEFERRAL";
  value: number;
  start_month: number;
}): Promise<SchedulePreview> {
  const params = new URLSearchParams({
    principal_cents: String(query.principal_cents),
    rate_bps: String(query.rate_bps),
    term: String(query.term),
    kind: query.kind,
    value: String(query.value),
    start_month: String(query.start_month),
  });
  return request(`/api/schedule/preview?${params.toString()}`);
}

export function getEvidence(hash: string): Promise<EvidenceCheck> {
  return request(`/api/evidence/${encodeURIComponent(hash)}`);
}

export interface AssistantReply {
  answer: string;
  facts_used: { label: string; value: string }[];
  source: "llm" | "llm+facts" | "template" | "cache";
  note?: string | null;
}

export function askAssistant(body: {
  question: string;
  season: number;
  week: number;
  loan_id?: number;
  audience?: "farmer" | "lender";
  evidence_prefix?: string;
}): Promise<AssistantReply> {
  return request("/api/assistant", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export interface WhatIfParse {
  ok: boolean;
  season_total_mm: number | null;
  pct_of_normal: number | null;
  message: string;
}

export function parseWhatIf(text: string): Promise<WhatIfParse> {
  return request("/api/whatif/parse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}
