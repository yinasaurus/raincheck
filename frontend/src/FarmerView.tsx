import { useEffect, useMemo, useRef, useState } from "react";
import { previewSchedule } from "./api";
import { AskSeason, WhatIfText } from "./ask";
import { ChartSwitch } from "./charts";
import { t, type Lang } from "./copy";
import { RainGauge, SeasonBar } from "./gauge";
import { useReducedMotion } from "./motion";
import {
  firstChanged,
  formatAmount,
  isNumber,
  normalToDate,
  reducedWindow,
  reliefSentence,
  showAmount,
  showChance,
  showMm,
  strictlyBelow,
  withoutRawProbability,
} from "./numbers";
import { statusMessage } from "./status";
import type { DemoRun, DemoYear } from "./types";

type Payish = { month: number; payment_cents: number; note?: string };

function SimLine({ lang, before, after }: { lang: Lang; before: Payish[]; after: Payish[] }) {
  const changed = firstChanged(before, after);
  if (!changed) return <p className="text-sm">{t(lang, "na")}</p>;
  return (
    <p className="text-sm">
      {t(lang, "thisMonth")}: {formatAmount(changed.before)} / {formatAmount(changed.after)} · {t(lang, "month")} {changed.month}
    </p>
  );
}

function roleLine(role: string, lang: Lang): string {
  if (role === "relief") return t(lang, "dry");
  if (role.toLowerCase().includes("false alarm")) return t(lang, "worried");
  return role;
}

function DataTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="max-w-full overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header} className="py-1 pr-3">
                {header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index} className="border-t border-line">
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="py-1 pr-3">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FarmerView({
  lang,
  years,
  selectedYear,
  onSelect,
  onRun,
  running,
  runStatus,
  demo,
  seasonTotal,
  paymentLine,
  onOpenRecord,
}: {
  lang: Lang;
  years: DemoYear[];
  selectedYear: number | null;
  onSelect: (year: number) => void;
  onRun: () => void;
  running: boolean;
  runStatus: number | null;
  demo: DemoRun | null;
  seasonTotal: number | null;
  paymentLine: number | null;
  onOpenRecord: () => void;
}) {
  const [week, setWeek] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [rain, setRain] = useState(1500);
  const [sim, setSim] = useState<{ before: Payish[]; after: Payish[] } | null>(null);
  const [simError, setSimError] = useState<number | null>(null);
  const replayRef = useRef<HTMLElement>(null);
  const reduceMotion = useReducedMotion();
  const observedRain = isNumber(demo?.rainfall_line?.observed_rainfall_mm) ? demo.rainfall_line.observed_rainfall_mm : null;
  const observedKey = demo && selectedYear !== null && demo.year === selectedYear ? observedRain : null;

  useEffect(() => {
    setWeek(1);
    setPlaying(false);
    setSim(null);
  }, [demo?.year]);

  useEffect(() => {
    const next = isNumber(observedKey) ? observedKey : seasonTotal;
    if (!isNumber(next)) return;
    setRain(Math.round(next * 10) / 10);
    setSim(null);
    setSimError(null);
  }, [selectedYear, seasonTotal, observedKey]);

  useEffect(() => {
    const node = replayRef.current;
    if (!demo?.loan?.id || !node || typeof node.scrollIntoView !== "function") return;
    node.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
  }, [demo?.loan?.id, reduceMotion]);

  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => setWeek((current) => (current >= 21 ? 21 : current + 1)), 900);
    return () => window.clearInterval(id);
  }, [playing]);

  useEffect(() => {
    if (week >= 21) setPlaying(false);
  }, [week]);

  const weeks = useMemo(
    () => (demo?.weekly ?? []).filter((row) => row.week_index >= 1 && row.week_index <= 21),
    [demo],
  );
  const current = weeks.find((row) => row.week_index === week) ?? null;
  const shown = weeks.filter((row) => row.week_index <= week);
  const line = isNumber(demo?.rainfall_line?.trigger_rainfall_mm) ? demo.rainfall_line.trigger_rainfall_mm : paymentLine;
  const before = (demo?.schedule_before ?? []) as Payish[];
  const after = (demo?.schedule_after ?? []) as Payish[];
  const changed = firstChanged(before, after);
  const paymentNow =
    changed ??
    (before[0] && after[0]
      ? { month: before[0].month, before: before[0].payment_cents, after: after[0].payment_cents }
      : null);
  const reliefWindow = reducedWindow(after);
  const fired = demo?.rainfall_line?.fired;
  const notice = statusMessage(runStatus, lang);

  const rainPoints = shown.map((row) => ({
    week: row.week_index,
    soFar: isNumber(row.cumulative_rainfall_mm) ? row.cumulative_rainfall_mm : null,
    normal: normalToDate(row.cumulative_rainfall_mm, row.rain_pct_of_normal),
  }));
  const fanPoints = shown.map((row) => {
    const band = row.projected_total_mm;
    const p10 = isNumber(band?.p10) ? band.p10 : null;
    const p90 = isNumber(band?.p90) ? band.p90 : null;
    return {
      week: row.week_index,
      p10,
      p90,
      p50: isNumber(band?.p50) ? band.p50 : null,
      span: p10 !== null && p90 !== null ? p90 - p10 : null,
    };
  });

  async function onRain(next: number) {
    setRain(next);
    setSim(null);
    setSimError(null);
    if (!isNumber(line) || !strictlyBelow(next, line) || !demo?.loan || !demo.example_relief) return;
    const relief = demo.example_relief;
    if (!isNumber(demo.loan.principal_cents) || !isNumber(demo.loan.annual_rate_bps) || !isNumber(demo.loan.term_months)) return;
    if (!isNumber(relief.value) || !isNumber(relief.start_month)) return;
    const kind = relief.kind === "DEFERRAL" ? "DEFERRAL" : "REDUCTION";
    try {
      const preview = await previewSchedule({
        principal_cents: demo.loan.principal_cents,
        rate_bps: demo.loan.annual_rate_bps,
        term: demo.loan.term_months,
        kind,
        value: relief.value,
        start_month: relief.start_month,
      });
      setSim({ before: preview.before, after: preview.after });
    } catch (error) {
      setSimError(error instanceof Error && "status" in error ? Number((error as { status: number }).status) : 0);
    }
  }

  const explanation = withoutRawProbability(current?.explanations?.[lang] ?? "");
  const matchesReplay = observedRain !== null && Math.abs(rain - observedRain) < 0.051;
  const matchedRelief =
    matchesReplay && fired === true && reliefWindow.count > 0 && reliefWindow.percent !== null
      ? reliefSentence(lang, reliefWindow.count, reliefWindow.percent)
      : null;
  const endMonth = demo?.summary?.relief_months;
  const baseMonth = demo?.summary?.baseline_months;

  return (
    <div className="space-y-6">
      <section>
        <h2 className="font-display text-2xl font-bold text-water">{t(lang, "pick")}</h2>
        {years.length === 0 ? <p className="mt-2 text-sm text-muted">{t(lang, "empty")}</p> : null}
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {years.map((item) => (
            <button
              key={item.year}
              type="button"
              onClick={() => onSelect(item.year)}
              className={`min-h-11 rounded-2xl border p-4 text-left ${selectedYear === item.year ? "border-water bg-panel" : "border-line bg-panel"}`}
            >
              <div className="font-display text-3xl font-bold text-water">{item.year}</div>
              <p className="mt-2 text-sm leading-6 text-muted">{roleLine(item.role, lang)}</p>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onRun}
          disabled={running || selectedYear === null}
          className="mt-4 min-h-11 rounded-xl bg-water px-5 text-panel disabled:opacity-50"
        >
          {running ? t(lang, "running") : t(lang, "run")}
        </button>
        {notice ? (
          <p role="alert" className="mt-2 text-sm text-ink">
            {notice}
          </p>
        ) : null}
        {runStatus !== null && runStatus !== 503 && runStatus !== 409 ? <p className="mt-2 text-sm text-ink">{t(lang, "failed")}</p> : null}
      </section>

      {!demo ? <p className="text-sm">{t(lang, "runFirst")}</p> : null}

      {demo ? (
        <section
          ref={replayRef}
          className="space-y-4 rounded-2xl border border-line bg-panel p-4"
          data-testid="replay"
          data-year={demo.year}
          data-loan={demo.loan?.id ?? ""}
        >
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => setPlaying((value) => !value)} className="min-h-11 rounded-xl border border-water px-4 text-water">
              {playing ? t(lang, "pause") : t(lang, "play")}
            </button>
            <label className="flex min-w-0 flex-1 items-center gap-3 text-sm">
              <span>
                {t(lang, "week")} {week}
              </span>
              <input
                type="range"
                min={1}
                max={21}
                step={1}
                value={week}
                aria-label={t(lang, "week")}
                onChange={(event) => {
                  setPlaying(false);
                  setWeek(Number(event.target.value));
                }}
                className="w-full"
              />
            </label>
          </div>

          <div className="grid items-center gap-4 sm:grid-cols-[16rem_minmax(0,1fr)]">
            <RainGauge
              soFar={isNumber(current?.cumulative_rainfall_mm) ? current.cumulative_rainfall_mm : null}
              usual={normalToDate(current?.cumulative_rainfall_mm, current?.rain_pct_of_normal)}
              low={isNumber(current?.projected_total_mm?.p10) ? current.projected_total_mm.p10 : null}
              high={isNumber(current?.projected_total_mm?.p90) ? current.projected_total_mm.p90 : null}
              line={line}
              lang={lang}
            />
            <div>
              <p className="text-sm text-muted">
                {lang === "fil" ? `Sa ika-${week} na linggo` : `${t(lang, "asOf")} ${week}`}
              </p>
              <p className="mt-3 text-sm text-muted">{t(lang, "rain")}</p>
              <p className="font-display text-5xl font-medium leading-none text-water">{showMm(current?.cumulative_rainfall_mm, lang)}</p>
              <p className="mt-3 text-sm text-muted">
                {t(lang, "usualNow")}: {showMm(normalToDate(current?.cumulative_rainfall_mm, current?.rain_pct_of_normal), lang)}
              </p>
              <p className="mt-4 text-sm text-muted">{t(lang, "chanceOf")}</p>
              <p className="font-display text-6xl font-medium leading-none text-water">{showChance(current?.p_relief, lang)}</p>
              <p className="mt-2 inline-block rounded-xl border border-water px-3 py-2 text-sm font-bold text-water">{t(lang, "advisory")}</p>
              {week < 12 ? <p className="mt-2 text-sm text-muted">{t(lang, "rough")}</p> : null}
              <p className="mt-2 text-sm leading-6 text-muted">{explanation || t(lang, "na")}</p>
            </div>
          </div>
          {lang === "en" ? <AskSeason season={demo.year} week={week} loanId={demo.loan?.id} /> : null}

          <ChartSwitch
            lang={lang}
            table={
              <DataTable
                headers={[t(lang, "week"), t(lang, "rain"), t(lang, "normal")]}
                rows={rainPoints.map((row) => [String(row.week), showMm(row.soFar, lang), showMm(row.normal, lang)])}
              />
            }
          >
            <p className="text-sm text-muted">
              {t(lang, "rain")}: {showMm(current?.cumulative_rainfall_mm, lang)} · {t(lang, "normal")}:{" "}
              {showMm(normalToDate(current?.cumulative_rainfall_mm, current?.rain_pct_of_normal), lang)}
            </p>
          </ChartSwitch>
          <ChartSwitch
            lang={lang}
            table={
              <DataTable
                headers={[t(lang, "week"), t(lang, "low"), t(lang, "mid"), t(lang, "high"), t(lang, "line")]}
                rows={fanPoints.map((row) => [
                  String(row.week),
                  showMm(row.p10, lang),
                  showMm(row.p50, lang),
                  showMm(row.p90, lang),
                  showMm(line, lang),
                ])}
              />
            }
          >
            <p className="text-sm text-muted">
              {t(lang, "fanTitle")}: {showMm(current?.projected_total_mm?.p10, lang)} – {showMm(current?.projected_total_mm?.p90, lang)}
            </p>
          </ChartSwitch>

          {week >= 21 ? (
            <div
              role="status"
              aria-live="polite"
              data-testid="season-banner"
              className={fired === true ? "space-y-3 rounded-xl bg-relief p-4 text-panel" : "space-y-3 rounded-xl border border-line bg-panel p-4 text-ink"}
            >
              <SeasonBar observed={isNumber(demo.rainfall_line?.observed_rainfall_mm) ? demo.rainfall_line.observed_rainfall_mm : null} line={line} />
              <h3 className="font-display text-2xl font-bold">{fired === true ? t(lang, "reliefApplied") : t(lang, "outcome")}</h3>
              <p className="text-sm leading-6">
                {fired === true && reliefWindow.count > 0 && reliefWindow.percent !== null
                  ? reliefSentence(lang, reliefWindow.count, reliefWindow.percent)
                  : fired === false
                    ? t(lang, "noRelief")
                    : t(lang, "na")}
              </p>
              <p className="text-sm leading-6">{t(lang, "depends")}</p>
              {fired === true ? <p className="text-sm leading-6">{t(lang, "debtMoves")}</p> : null}
              <p className="text-sm">
                {showMm(demo.rainfall_line?.observed_rainfall_mm, lang)} / {showMm(line, lang)}
              </p>
            </div>
          ) : null}

          <div>
            <h3 className="font-display text-xl font-bold text-water">{t(lang, "payments")}</h3>
            {demo.loan?.principal_cents === 10_000_000 ? <p className="text-sm">{t(lang, "exampleLoan")}</p> : null}
            <p className="mt-2 text-sm">{t(lang, "thisMonth")}</p>
            <p className="font-display text-3xl font-medium text-water">
              {paymentNow
                ? `${t(lang, "month")} ${paymentNow.month}: ${formatAmount(paymentNow.before)} ${t(lang, "before").toLowerCase()} / ${formatAmount(paymentNow.after)} ${t(lang, "after").toLowerCase()}`
                : t(lang, "na")}
            </p>
            <p className="mt-2 text-sm">
              {t(lang, "totalRepaid")}: {showAmount(demo.summary?.baseline_total_paid_cents, lang)} {t(lang, "before").toLowerCase()} /{" "}
              {showAmount(demo.summary?.relief_total_paid_cents, lang)} {t(lang, "after").toLowerCase()}
              {isNumber(demo.summary?.extra_cost_cents) ? ` (+${formatAmount(demo.summary.extra_cost_cents)})` : ""}
            </p>
            <p className="text-sm">
              {t(lang, "ends")} {isNumber(endMonth) ? endMonth : t(lang, "na")}
              {isNumber(endMonth) && isNumber(baseMonth) && endMonth !== baseMonth ? ` ${t(lang, "insteadOf")} ${baseMonth}` : ""}
            </p>
          </div>

          <button type="button" onClick={onOpenRecord} className="min-h-11 rounded-xl border border-water px-4 text-sm text-water">
            {t(lang, "seeRecord")}
          </button>
        </section>
      ) : null}

      <section className="rounded-2xl border border-line bg-panel p-4" data-testid="what-if">
        <h2 className="font-display text-xl font-bold text-water">{t(lang, "whatIf")}</h2>
        <label className="mt-2 block text-sm">
          {t(lang, "slider")}: {rain.toLocaleString("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 })} {t(lang, "mm")}
          <input
            type="range"
            min={900}
            max={2200}
            step={0.1}
            value={rain}
            aria-label={t(lang, "slider")}
            onChange={(event) => void onRain(Number(event.target.value))}
            className="mt-2 min-h-11 w-full"
          />
        </label>
        {lang === "en" ? <WhatIfText onPick={(millimetres) => void onRain(millimetres)} /> : null}
        <p className="mt-2 text-sm">
          {matchedRelief
            ? matchedRelief
            : matchesReplay && fired === false
              ? t(lang, "noRelief")
              : !isNumber(line)
                ? t(lang, "na")
                : strictlyBelow(rain, line)
                  ? t(lang, "wouldRelief")
                  : t(lang, "wouldNot")}
        </p>
        {matchesReplay && fired === true ? <p className="text-sm">{t(lang, "depends")}</p> : null}
        {statusMessage(simError, lang) ? <p className="text-sm text-ink">{statusMessage(simError, lang)}</p> : null}
        {isNumber(line) && !matchesReplay && !strictlyBelow(rain, line) ? <p className="text-sm">{t(lang, "unchanged")}</p> : null}
        {sim ? (
          <SimLine lang={lang} before={sim.before} after={sim.after} />
        ) : null}
      </section>
    </div>
  );
}
