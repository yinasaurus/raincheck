import { useMemo, useState } from "react";
import { getEvidence } from "./api";
import { ChartSwitch, TrendChart } from "./charts";
import { t, type Lang } from "./copy";
import { useReducedMotion } from "./motion";
import { isNumber, showChance, showMm } from "./numbers";
import { statusMessage } from "./status";
import type { BacktestBody, BacktestRow, DemoRun, EvidenceCheck, RiskBody } from "./types";

const SKILL_WEEKS = ["4", "8", "12", "16", "21"];
type SortKey = "year" | "total" | "fired" | "alarm";

function tags(year: number, lang: Lang): string[] {
  const marks: string[] = [];
  if (year === 2004 || year === 2017 || year === 2020) marks.push(t(lang, "demoTag"));
  if (year >= 2018 && year <= 2026) marks.push(t(lang, "recentTag"));
  return marks;
}

function CopyButton({ value, lang }: { value: string | null | undefined; lang: Lang }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span>{t(lang, "na")}</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span className="break-all">{value}</span>
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard.writeText(value).then(
            () => {
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            },
            () => setCopied(false),
          );
        }}
        className="min-h-11 rounded-xl border border-water px-3 text-sm text-water"
      >
        {copied ? t(lang, "copied") : t(lang, "copy")}
      </button>
    </span>
  );
}

export function LenderView({
  lang,
  demo,
  backtest,
  risk,
  runStatus,
}: {
  lang: Lang;
  demo: DemoRun | null;
  backtest: BacktestBody | null;
  risk: RiskBody | null;
  runStatus: number | null;
}) {
  const reduce = useReducedMotion();
  const [check, setCheck] = useState<EvidenceCheck | null>(null);
  const [checkStatus, setCheckStatus] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>("year");
  const [sortAsc, setSortAsc] = useState(true);
  const meta = backtest?.metadata;
  const candidates = backtest?.candidates ?? {};
  const names = Object.keys(candidates).sort((a, b) => {
    if (a === "climatology") return 1;
    if (b === "climatology") return -1;
    return (candidates[a]?.mean_brier_without_week_21 ?? 99) - (candidates[b]?.mean_brier_without_week_21 ?? 99);
  });
  const end = demo?.weekly?.find((row) => row.week_index === 21) ?? demo?.weekly?.at(-1);
  const line = isNumber(demo?.rainfall_line?.trigger_rainfall_mm) ? demo.rainfall_line.trigger_rainfall_mm : backtest?.payment_line_mm;
  const year2017 = backtest?.rows?.find((row) => row.year === 2017);
  const year2020 = backtest?.rows?.find((row) => row.year === 2020);

  const rows = useMemo(() => {
    const list = [...(backtest?.rows ?? [])];
    const dir = sortAsc ? 1 : -1;
    list.sort((a, b) => {
      const left = sortValue(a, sortKey);
      const right = sortValue(b, sortKey);
      return left < right ? -dir : left > right ? dir : 0;
    });
    return list;
  }, [backtest, sortKey, sortAsc]);

  function sort(next: SortKey) {
    if (next === sortKey) setSortAsc((value) => !value);
    else {
      setSortKey(next);
      setSortAsc(true);
    }
  }

  async function verify() {
    const hash = demo?.oracle?.evidence_hash;
    if (!hash) return;
    setChecking(true);
    setCheckStatus(null);
    try {
      setCheck(await getEvidence(hash));
    } catch (error) {
      setCheck(null);
      setCheckStatus(error instanceof Error && "status" in error ? Number((error as { status: number }).status) : 0);
    } finally {
      setChecking(false);
    }
  }

  return (
    <div className="space-y-6">
      {statusMessage(runStatus, lang) ? <p role="alert" className="text-sm text-ink">{statusMessage(runStatus, lang)}</p> : null}

      <section className="rounded-2xl border border-line bg-panel p-4">
        <h2 className="font-display font-bold text-water text-2xl">{t(lang, "terms")}</h2>
        {demo?.loan ? (
          <dl className="mt-3 grid gap-2 text-sm sm:grid-cols-2">
            <Field label={t(lang, "loanId")} value={text(demo.loan.id, lang)} />
            <Field label={t(lang, "principal")} value={text(demo.loan.principal_cents, lang)} />
            <Field label={t(lang, "rate")} value={text(demo.loan.annual_rate_bps, lang)} />
            <Field label={t(lang, "term")} value={text(demo.loan.term_months, lang)} />
            <Field label={t(lang, "triggerTenths")} value={text(demo.loan.trigger_rainfall_tenths_mm, lang)} />
            <Field label={t(lang, "maxCut")} value={text(demo.loan.max_reduction_bps, lang)} />
            <Field label={t(lang, "maxSkip")} value={text(demo.loan.max_deferral_months, lang)} />
            <div>
              <dt className="text-muted">{t(lang, "createTx")}</dt>
              <dd>
                <CopyButton value={demo.loan.create_tx_hash} lang={lang} />
              </dd>
            </div>
          </dl>
        ) : (
          <p className="mt-2 text-sm">{t(lang, "na")}</p>
        )}
      </section>

      <section className="rounded-2xl border border-line bg-panel p-4">
        <h2 className="font-display font-bold text-water text-2xl">{t(lang, "events")}</h2>
        {demo?.oracle ? (
          <div className="mt-3 space-y-2 text-sm">
            <p>{demo.oracle.relief_applied ? t(lang, "applied") : t(lang, "notApplied")}</p>
            <p>{demo.oracle.reason || t(lang, "na")}</p>
            <p>
              {t(lang, "tx")}: <CopyButton value={demo.oracle.tx_hash} lang={lang} />
            </p>
            <p>
              {t(lang, "evidence")}: <CopyButton value={demo.oracle.evidence_hash} lang={lang} />
            </p>
            <button type="button" onClick={() => void verify()} disabled={!demo.oracle.evidence_hash || checking} className="min-h-11 rounded-xl border border-water px-4 text-water disabled:opacity-50">
              {checking ? t(lang, "verifying") : t(lang, "verify")}
            </button>
            {statusMessage(checkStatus, lang) ? <p className="text-ink">{statusMessage(checkStatus, lang)}</p> : null}
            {check ? (
              <p data-testid="verify-result">
                {check.matches ? t(lang, "match") : t(lang, "mismatch")} {check.recomputed_hash || t(lang, "na")}
              </p>
            ) : null}
          </div>
        ) : (
          <p className="mt-2 text-sm">{t(lang, "na")}</p>
        )}
      </section>

      <section className="rounded-2xl border border-line bg-panel p-4" aria-labelledby="advises-title">
        <h2 id="advises-title" className="font-display font-bold text-water text-2xl">
          {t(lang, "advises")}
        </h2>
        <h3 className="mt-3 font-display text-xl font-bold text-water">
          {t(lang, "currentSeason")} {isNumber(risk?.season_year) ? risk.season_year : t(lang, "na")}
        </h3>
        <p className="mt-2 text-sm leading-6">{risk?.explanations?.[lang] || t(lang, "na")}</p>
        <dl className="mt-3 space-y-1 text-sm">
          <div>
            <dt>{t(lang, "modelRow")}</dt>
            <dd>
              {showChance(end?.p_relief, lang)}
              {isNumber(end?.p_relief) ? ` (${end.p_relief.toFixed(4)})` : ""}
            </dd>
          </div>
          <div>
            <dt>{t(lang, "ruleRow")}</dt>
            <dd>
              {showChance(end?.rule_score, lang)}
              {isNumber(end?.rule_score) ? ` (${end.rule_score.toFixed(4)})` : ""}
            </dd>
          </div>
          <div>
            <dt>{t(lang, "observedRow")}</dt>
            <dd>
              {showMm(demo?.rainfall_line?.observed_rainfall_mm, lang)} / {showMm(line, lang)}.{" "}
              {demo?.rainfall_line?.fired === true ? t(lang, "below") : demo?.rainfall_line?.fired === false ? t(lang, "notBelow") : t(lang, "na")}
            </dd>
          </div>
        </dl>
        <p className="mt-3 text-sm leading-6">{yearNote(2017, year2017, lang)}</p>
        <p className="mt-2 text-sm leading-6">{yearNote(2020, year2020, lang)}</p>
      </section>

      <section className="rounded-2xl border border-line bg-panel p-4">
        <h2 className="font-display font-bold text-water text-2xl">{t(lang, "backtest")}</h2>
        <p className="mt-1 text-sm leading-6">{t(lang, "threeOf")}</p>
        <div className="mt-3 max-w-full overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <SortHead label={t(lang, "year")} active={sortKey === "year"} onClick={() => sort("year")} />
                <SortHead label={t(lang, "total")} active={sortKey === "total"} onClick={() => sort("total")} />
                <SortHead label={t(lang, "fired")} active={sortKey === "fired"} onClick={() => sort("fired")} />
                {SKILL_WEEKS.map((week) => (
                  <th key={week} className="py-1 pr-3">
                    w{week}
                  </th>
                ))}
                <th className="py-1 pr-3">{t(lang, "first")}</th>
                <SortHead label={t(lang, "falseAlarm")} active={sortKey === "alarm"} onClick={() => sort("alarm")} />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.year} className={`border-t border-line ${tags(row.year, lang).length ? "bg-ground" : ""}`}>
                  <td className="py-1 pr-3">
                    {row.year}
                    {tags(row.year, lang).length ? <span className="ml-1 text-xs">({tags(row.year, lang).join(", ")})</span> : null}
                  </td>
                  <td className="py-1 pr-3">{showMm(row.season_total_mm, lang)}</td>
                  <td className="py-1 pr-3">{row.relief_fired ? t(lang, "yes") : t(lang, "no")}</td>
                  {SKILL_WEEKS.map((week) => (
                    <td key={week} className="py-1 pr-3">
                      {showChance(row.p_relief?.[week], lang)}
                    </td>
                  ))}
                  <td className="py-1 pr-3">{row.first_week_p_relief_at_least_0_5 ?? t(lang, "na")}</td>
                  <td className="py-1">{row.false_alarm ? t(lang, "yes") : t(lang, "no")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-2xl border border-line bg-panel p-4">
        <h2 className="font-display font-bold text-water text-2xl">{t(lang, "trend")}</h2>
        <p className="mt-1 text-sm leading-6">{backtest?.trend?.trend_note || t(lang, "na")}</p>
        <ChartSwitch
          lang={lang}
          table={
            <div className="max-w-full overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    <th className="py-1 pr-3">{t(lang, "year")}</th>
                    <th className="py-1 pr-3">{t(lang, "total")}</th>
                    <th className="py-1">{t(lang, "rolling")}</th>
                  </tr>
                </thead>
                <tbody>
                  {(backtest?.trend?.season_totals_mm ?? []).map((row) => (
                    <tr key={row.year} className="border-t border-line">
                      <td className="py-1 pr-3">{row.year}</td>
                      <td className="py-1 pr-3">{showMm(row.season_total_mm, lang)}</td>
                      <td className="py-1">
                        {showMm(backtest?.trend?.rolling_10_year_mean_mm?.find((item) => item.end_year === row.year)?.mean_mm, lang)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          }
        >
          <TrendChart
            lang={lang}
            animate={!reduce}
            totals={backtest?.trend?.season_totals_mm ?? []}
            rolling={backtest?.trend?.rolling_10_year_mean_mm ?? []}
            line={isNumber(backtest?.payment_line_mm) ? backtest.payment_line_mm : null}
          />
        </ChartSwitch>
      </section>

      <section className="rounded-2xl border border-line bg-panel p-4">
        <h2 className="font-display font-bold text-water text-2xl">{t(lang, "compare")}</h2>
        <p className="mt-2 text-sm leading-6">{backtest?.small_sample_note || t(lang, "na")}</p>
        <p className="text-sm leading-6">{meta?.selection_bias || t(lang, "na")}</p>
        <div className="mt-3 max-w-full overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr>
                <th className="py-1 pr-3">{t(lang, "candidate")}</th>
                <th className="py-1 pr-3">{t(lang, "headline")}</th>
                <th className="py-1 pr-3">{t(lang, "with21")}</th>
                {SKILL_WEEKS.map((week) => (
                  <th key={week} className="py-1 pr-3">
                    {t(lang, "skill")} {week}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {names.map((name) => (
                <tr key={name} className="border-t border-line">
                  <td className="py-1 pr-3">{name}</td>
                  <td className="py-1 pr-3">{plain(candidates[name]?.mean_brier_without_week_21, lang)}</td>
                  <td className="py-1 pr-3">{plain(candidates[name]?.mean_brier_with_week_21, lang)}</td>
                  {SKILL_WEEKS.map((week) => (
                    <td key={week} className="py-1 pr-3">
                      {plain(candidates[name]?.by_week?.[week]?.brier_skill, lang)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-sm">
          {t(lang, "climoBrier")}: {SKILL_WEEKS.map((week) => `w${week} ${plain(meta?.climatology_brier_by_week?.[week], lang)}`).join(" · ")}
        </p>
      </section>
    </div>
  );
}

function yearNote(year: number, row: BacktestRow | undefined, lang: Lang): string {
  if (!row) return `${year}: ${t(lang, "na")}`;
  const first = row.first_week_p_relief_at_least_0_5 ?? t(lang, "na");
  const total = showMm(row.season_total_mm, lang);
  if (year === 2020) {
    return lang === "fil"
      ? `2020: umabot ang tantya sa 0.5 noong linggo ${first}, pero ${total} ang natapos na ulan, kaya walang relief. Maling alarma ito.`
      : `2020: the estimate reached 0.5 at week ${first}, but the season finished at ${total}, so there was no relief. That is a false alarm.`;
  }
  return lang === "fil"
    ? `2017: ${total} ang natapos na ulan, mas mababa sa linya, kaya may relief. Umabot ang tantya sa 0.5 noong linggo ${first}. Ang nasukat na ulan ang nagpasya, hindi ang tantya.`
    : `2017: the season finished at ${total}, below the line, so relief applies. The estimate reached 0.5 at week ${first}. Measured rainfall decided it, not the estimate.`;
}

function sortValue(row: BacktestRow, key: SortKey): number {
  if (key === "total") return row.season_total_mm ?? -1;
  if (key === "fired") return row.relief_fired ? 1 : 0;
  if (key === "alarm") return row.false_alarm ? 1 : 0;
  return row.year;
}

function SortHead({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <th className="py-1 pr-3">
      <button type="button" onClick={onClick} className="min-h-11 underline" aria-pressed={active}>
        {label}
      </button>
    </th>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="break-all">{value}</dd>
    </div>
  );
}

function text(value: unknown, lang: Lang): string {
  if (value === null || value === undefined || value === "") return t(lang, "na");
  return String(value);
}

function plain(value: unknown, lang: Lang): string {
  if (!isNumber(value)) return t(lang, "na");
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}
