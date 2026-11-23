import { useEffect, useMemo, useState } from "react";
import { previewSchedule } from "./api";
import { ChartSwitch, FanChart, RainChart } from "./charts";
import { t, type Lang } from "./copy";
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
} from "./numbers";
import { statusMessage } from "./status";
import type { DemoRun, DemoYear, RiskBody } from "./types";

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
            <tr key={index} className="border-t border-stone-200">
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
  risk,
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
  risk: RiskBody | null;
  paymentLine: number | null;
  onOpenRecord: () => void;
}) {
  const reduce = useReducedMotion();
  const [week, setWeek] = useState(1);
  const [playing, setPlaying] = useState(false);
  const [rain, setRain] = useState(1500);
  const [sim, setSim] = useState<{ before: Payish[]; after: Payish[] } | null>(null);
  const [simError, setSimError] = useState<number | null>(null);

  useEffect(() => {
    setWeek(1);
    setPlaying(false);
    setSim(null);
  }, [demo?.year]);

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

  const explanation = current?.explanations?.[lang];
  const endMonth = demo?.summary?.relief_months;
  const baseMonth = demo?.summary?.baseline_months;

  return (
    <div className="space-y-6">
      <section>
        <h2 className="font-serif text-2xl">{t(lang, "pick")}</h2>
        {years.length === 0 ? <p className="mt-2 text-sm">{t(lang, "empty")}</p> : null}
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {years.map((item) => (
            <button
              key={item.year}
              type="button"
              onClick={() => onSelect(item.year)}
              className={`rounded-2xl border p-4 text-left ${selectedYear === item.year ? "border-field bg-white" : "border-stone-300 bg-card"}`}
            >
              <div className="font-serif text-3xl">{item.year}</div>
              <p className="mt-2 text-sm leading-6">{roleLine(item.role, lang)}</p>
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={onRun}
          disabled={running || selectedYear === null}
          className="mt-4 rounded-full bg-field px-5 py-3 text-white disabled:opacity-50"
        >
          {running ? t(lang, "running") : t(lang, "run")}
        </button>
        {notice ? (
          <p role="alert" className="mt-2 text-sm text-clay">
            {notice}
          </p>
        ) : null}
        {runStatus !== null && runStatus !== 503 && runStatus !== 409 ? <p className="mt-2 text-sm text-clay">{t(lang, "failed")}</p> : null}
      </section>

      {risk ? (
        <section className="rounded-2xl border border-stone-300 bg-card p-4">
          <h2 className="font-serif text-xl">
            {t(lang, "latest")} {isNumber(risk.season_year) ? risk.season_year : t(lang, "na")}
          </h2>
          <p className="mt-2 text-sm leading-6">{risk.explanations?.[lang] || t(lang, "na")}</p>
        </section>
      ) : null}

      {!demo ? <p className="text-sm">{t(lang, "runFirst")}</p> : null}

      {demo ? (
        <section
          className="space-y-4 rounded-2xl border border-stone-300 bg-card p-4"
          data-testid="replay"
          data-year={demo.year}
          data-loan={demo.loan?.id ?? ""}
        >
          <div className="flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => setPlaying((value) => !value)} className="rounded-full border border-ink px-4 py-2">
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

          <div>
            <p className="text-sm text-stone-700">
              {lang === "fil" ? `Sa ika-${week} na linggo` : `${t(lang, "asOf")} ${week}`}
            </p>
            <p className="text-sm uppercase tracking-wide text-stone-700">{t(lang, "chance")}</p>
            <p className="font-serif text-7xl leading-none">{showChance(current?.p_relief, lang)}</p>
            <p className="mt-1 text-sm font-medium text-clay">{t(lang, "advisory")}</p>
            {week < 12 ? <p className="mt-1 text-sm">{t(lang, "rough")}</p> : null}
            <p className="mt-2 text-sm">
              {t(lang, "rule")}: {showChance(current?.rule_score, lang)}
            </p>
            <p className="mt-2 text-sm leading-6">{explanation || t(lang, "na")}</p>
          </div>

          <div>
            <h3 className="font-serif text-xl">{t(lang, "rainTitle")}</h3>
            <ChartSwitch
              lang={lang}
              table={
                <DataTable
                  headers={[t(lang, "week"), t(lang, "rain"), t(lang, "normal")]}
                  rows={rainPoints.map((row) => [String(row.week), showMm(row.soFar, lang), showMm(row.normal, lang)])}
                />
              }
            >
              <RainChart points={rainPoints} lang={lang} animate={!reduce} />
            </ChartSwitch>
            <p className="text-sm">
              {t(lang, "rain")}: {showMm(current?.cumulative_rainfall_mm, lang)} · {t(lang, "normal")}:{" "}
              {showMm(normalToDate(current?.cumulative_rainfall_mm, current?.rain_pct_of_normal), lang)}
            </p>
          </div>

          <div>
            <h3 className="font-serif text-xl">{t(lang, "fanTitle")}</h3>
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
              <FanChart points={fanPoints} line={line} lang={lang} animate={!reduce} />
            </ChartSwitch>
          </div>

          {week >= 21 ? (
            <div aria-live="polite" data-testid="season-banner" className="rounded-xl border border-ink p-3">
              <h3 className="font-serif text-xl">{t(lang, "outcome")}</h3>
              <p className="mt-1 text-sm leading-6">
                {fired === true && reliefWindow.count > 0 && reliefWindow.percent !== null
                  ? reliefSentence(lang, reliefWindow.count, reliefWindow.percent)
                  : fired === false
                    ? t(lang, "noRelief")
                    : t(lang, "na")}
              </p>
              <p className="text-sm leading-6">{t(lang, "depends")}</p>
              <p className="text-sm">
                {showMm(demo.rainfall_line?.observed_rainfall_mm, lang)} / {showMm(line, lang)}
              </p>
            </div>
          ) : null}

          <div>
            <h3 className="font-serif text-xl">{t(lang, "payments")}</h3>
            {demo.loan?.principal_cents === 10_000_000 ? <p className="text-sm">{t(lang, "exampleLoan")}</p> : null}
            <p className="mt-2 text-sm">{t(lang, "thisMonth")}</p>
            <p className="font-serif text-3xl">
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

          <button type="button" onClick={onOpenRecord} className="rounded-full border border-ink px-4 py-2 text-sm">
            {t(lang, "seeRecord")}
          </button>
        </section>
      ) : null}

      <section className="rounded-2xl border border-stone-300 bg-card p-4">
        <h2 className="font-serif text-xl">{t(lang, "whatIf")}</h2>
        <p className="text-sm font-medium">{t(lang, "simulation")}</p>
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
            className="mt-2 w-full"
          />
        </label>
        <p className="mt-2 text-sm">
          {!isNumber(line) ? t(lang, "na") : strictlyBelow(rain, line) ? t(lang, "wouldRelief") : t(lang, "wouldNot")}
        </p>
        {statusMessage(simError, lang) ? <p className="text-sm text-clay">{statusMessage(simError, lang)}</p> : null}
        {isNumber(line) && !strictlyBelow(rain, line) ? <p className="text-sm">{t(lang, "unchanged")}</p> : null}
        {sim ? (
          <SimLine lang={lang} before={sim.before} after={sim.after} />
        ) : null}
      </section>
    </div>
  );
}
