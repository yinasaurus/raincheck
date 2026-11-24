import { useState } from "react";
import { ApiError, askAssistant, parseWhatIf, type AssistantReply } from "./api";
import { t, type Lang } from "./copy";

const CHIPS = ["askChance", "askWhy", "askPay", "askLimits"] as const;

export function AskSeason({ season, week, loanId }: { season: number; week: number; loanId?: number }) {
  const lang: Lang = "en";
  const [question, setQuestion] = useState("");
  const [reply, setReply] = useState<AssistantReply | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  async function ask(text: string) {
    const trimmed = text.trim().slice(0, 200);
    if (!trimmed) return;
    setQuestion(trimmed);
    setLoading(true);
    setStatus(null);
    try {
      const next = await askAssistant({ question: trimmed, season, week, loan_id: loanId, audience: "farmer" });
      setReply(next);
    } catch (error) {
      setReply(null);
      setStatus(error instanceof ApiError ? error.status : 503);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="space-y-3 rounded-2xl border border-line bg-panel p-4" data-testid="ask-season">
      <h3 className="font-display text-xl font-bold text-water">{t(lang, "askTitle")}</h3>
      <div className="flex flex-wrap gap-2">
        {CHIPS.map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => void ask(t(lang, key))}
            className="min-h-11 rounded-xl border border-water px-3 text-left text-sm text-water"
          >
            {t(lang, key)}
          </button>
        ))}
      </div>
      <form
        className="flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          void ask(question);
        }}
      >
        <label className="min-w-0 flex-1 text-sm">
          <input
            value={question}
            maxLength={200}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder={t(lang, "askPlaceholder")}
            aria-label={t(lang, "askPlaceholder")}
            className="min-h-11 w-full rounded-xl border border-line bg-panel px-3"
          />
        </label>
        <button type="submit" className="min-h-11 rounded-xl bg-water px-4 text-panel" disabled={loading || question.trim() === ""}>
          {t(lang, "askSend")}
        </button>
      </form>
      <div aria-live="polite" className="space-y-2 text-sm leading-6">
        {loading ? <p>{t(lang, "askLoading")}</p> : null}
        {status === 429 ? <p role="alert">{t(lang, "askBusy")}</p> : null}
        {status !== null && status !== 429 ? <p role="alert">{t(lang, "askError")}</p> : null}
        {reply ? (
          <div data-testid="ask-answer" data-source={reply.source}>
            {reply.note ? <p>{reply.note}</p> : null}
            {reply.source === "template" && !reply.note ? <p>{t(lang, "askBusy")}</p> : null}
            <p>{reply.answer}</p>
            <p className="text-muted">{t(lang, "askBased")}</p>
            <ul className="max-h-40 list-disc overflow-y-auto pl-5">
              {reply.facts_used.map((fact) => (
                <li key={fact.label}>
                  {fact.label}: {fact.value}
                </li>
              ))}
            </ul>
            <p className="text-muted">{t(lang, "askLabel")}</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}

export function WhatIfText({ onPick }: { onPick: (millimetres: number) => void }) {
  const lang: Lang = "en";
  const [text, setText] = useState("");
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit() {
    setLoading(true);
    setStatus(null);
    try {
      const parsed = await parseWhatIf(text.slice(0, 200));
      setMessage(parsed.message);
      if (parsed.ok && typeof parsed.season_total_mm === "number") onPick(parsed.season_total_mm);
    } catch (error) {
      setMessage("");
      setStatus(error instanceof ApiError ? error.status : 503);
    } finally {
      setLoading(false);
    }
  }

  return (
    <form
      className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-end"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <label className="min-w-0 flex-1 text-sm">
        {t(lang, "askWhat")}
        <input
          value={text}
          maxLength={200}
          onChange={(event) => setText(event.target.value)}
          aria-label={t(lang, "askWhat")}
          className="mt-1 min-h-11 w-full rounded-xl border border-line bg-panel px-3"
        />
      </label>
      <button type="submit" className="min-h-11 rounded-xl border border-water px-4 text-water" disabled={loading || text.trim() === ""}>
        {t(lang, "askApply")}
      </button>
      <div aria-live="polite" className="min-w-0 text-sm sm:basis-full">
        {status === 429 ? <p>{t(lang, "askBusy")}</p> : null}
        {message ? <p>{message}</p> : null}
      </div>
    </form>
  );
}

export function AuditNote({
  season,
  loanId,
  evidenceHash,
}: {
  season: number;
  loanId?: number;
  evidenceHash?: string | null;
}) {
  const lang: Lang = "en";
  const [reply, setReply] = useState<AssistantReply | null>(null);
  const [status, setStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [started, setStarted] = useState(false);

  async function load() {
    setStarted(true);
    setLoading(true);
    setStatus(null);
    try {
      const prefix = evidenceHash ? evidenceHash.slice(0, 10) : undefined;
      const next = await askAssistant({
        question: "Write the audit note.",
        season,
        week: 21,
        loan_id: loanId,
        audience: "lender",
        evidence_prefix: prefix,
      });
      setReply(next);
    } catch (error) {
      setReply(null);
      setStatus(error instanceof ApiError ? error.status : 503);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-2 text-sm leading-6" data-testid="audit-note">
      <h3 className="font-display text-xl font-bold text-water">{t(lang, "auditTitle")}</h3>
      {!started ? (
        <button type="button" onClick={() => void load()} className="min-h-11 rounded-xl border border-water px-4 text-water">
          {t(lang, "auditTitle")}
        </button>
      ) : null}
      <div aria-live="polite">
        {loading ? <p>{t(lang, "askLoading")}</p> : null}
        {status === 429 ? <p>{t(lang, "askBusy")}</p> : null}
        {status !== null && status !== 429 ? <p>{t(lang, "askError")}</p> : null}
        {reply ? (
          <>
            {reply.note ? <p>{reply.note}</p> : null}
            <p>{reply.answer}</p>
            <p className="text-muted">{t(lang, "auditLabel")}</p>
          </>
        ) : null}
      </div>
    </div>
  );
}
