import { useEffect, useState } from "react";
import { ApiError, getBacktest, getDemoYears, getRegion, getRisk, getValidation, runDemo } from "./api";
import { t, type Lang } from "./copy";
import { FarmerView } from "./FarmerView";
import { LenderView } from "./LenderView";
import { LimitsPanel } from "./LimitsPanel";
import { isNumber } from "./numbers";
import type { BacktestBody, DemoRun, DemoYear, RegionBody, RiskBody, ValidationBody } from "./types";

type Audience = "farmer" | "lender";

export default function App() {
  const [lang, setLang] = useState<Lang>("en");
  const [audience, setAudience] = useState<Audience>("farmer");
  const [years, setYears] = useState<DemoYear[]>([]);
  const [region, setRegion] = useState<RegionBody | null>(null);
  const [backtest, setBacktest] = useState<BacktestBody | null>(null);
  const [validation, setValidation] = useState<ValidationBody | null>(null);
  const [risk, setRisk] = useState<RiskBody | null>(null);
  const [loadStatus, setLoadStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [demo, setDemo] = useState<DemoRun | null>(null);
  const [running, setRunning] = useState(false);
  const [runStatus, setRunStatus] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([getDemoYears(), getRegion(), getBacktest(), getRisk(), getValidation()]).then((results) => {
      if (cancelled) return;
      const [yearResult, regionResult, backtestResult, riskResult, validationResult] = results;
      if (yearResult.status === "fulfilled") {
        setYears(yearResult.value.years);
        setSelectedYear(yearResult.value.years[0]?.year ?? null);
      }
      if (regionResult.status === "fulfilled") setRegion(regionResult.value);
      if (backtestResult.status === "fulfilled") setBacktest(backtestResult.value);
      if (riskResult.status === "fulfilled") setRisk(riskResult.value);
      if (validationResult.status === "fulfilled") setValidation(validationResult.value);
      const failed = results.find((result) => result.status === "rejected");
      if (failed && failed.status === "rejected") {
        setLoadStatus(failed.reason instanceof ApiError ? failed.reason.status : 0);
      }
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function onRun() {
    if (selectedYear === null) return;
    setRunning(true);
    setRunStatus(null);
    try {
      setDemo(await runDemo(selectedYear));
    } catch (error) {
      setDemo(null);
      setRunStatus(error instanceof ApiError ? error.status : 0);
    } finally {
      setRunning(false);
    }
  }

  const place = region?.name && region?.crop ? `${region.name} · ${region.crop}` : t(lang, "na");
  const paymentLine = backtest?.payment_line_mm ?? region?.trigger?.proposed_trigger_rainfall_mm ?? null;
  const seasonTotal = backtest?.rows?.find((row) => row.year === selectedYear)?.season_total_mm ?? null;

  return (
    <div className="min-h-screen overflow-x-hidden bg-ground text-ink">
      <header className="border-b border-line bg-panel">
        <div className="site-header mx-auto max-w-6xl px-4 py-4">
          <div className="site-brand">
            <h1 className="font-display text-2xl font-bold text-water">{t(lang, "name")}</h1>
            <p className="text-sm text-muted">{place}</p>
          </div>
          <div className="site-lang flex gap-2 rounded-xl border border-line p-1" role="group" aria-label={t(lang, "english")}>
            <button type="button" onClick={() => setLang("en")} className={`min-h-11 rounded-xl px-3 text-sm ${lang === "en" ? "bg-ground" : ""}`}>
              {t(lang, "english")}
            </button>
            <button type="button" onClick={() => setLang("fil")} className={`min-h-11 rounded-xl px-3 text-sm ${lang === "fil" ? "bg-ground" : ""}`}>
              {t(lang, "filipino")}
            </button>
          </div>
          <div className="site-audience flex gap-2 rounded-xl border border-line p-1" role="group" aria-label={t(lang, "farmer")}>
            <button type="button" onClick={() => setAudience("farmer")} className={`min-h-11 rounded-xl px-3 text-sm ${audience === "farmer" ? "bg-water text-panel" : "text-ink"}`}>
              {t(lang, "farmer")}
            </button>
            <button type="button" onClick={() => setAudience("lender")} className={`min-h-11 rounded-xl px-3 text-sm ${audience === "lender" ? "bg-water text-panel" : "text-ink"}`}>
              {t(lang, "lender")}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          {loadStatus === 503 ? (
            <p role="alert" className="mb-3 text-sm text-ink">
              {t(lang, "down")}
            </p>
          ) : null}
          {loading ? (
            <div aria-busy="true" aria-label={t(lang, "loading")} className="space-y-3">
              <div className="h-24 animate-pulse rounded-2xl bg-line" />
              <div className="h-24 animate-pulse rounded-2xl bg-line" />
              <div className="h-24 animate-pulse rounded-2xl bg-line" />
            </div>
          ) : audience === "farmer" ? (
            <FarmerView
              lang={lang}
              years={years}
              selectedYear={selectedYear}
              onSelect={setSelectedYear}
              onRun={() => void onRun()}
              running={running}
              runStatus={runStatus}
              demo={demo}
              seasonTotal={isNumber(seasonTotal) ? seasonTotal : null}
              paymentLine={paymentLine}
              onOpenRecord={() => setAudience("lender")}
            />
          ) : (
            <LenderView lang={lang} demo={demo} backtest={backtest} validation={validation} risk={risk} runStatus={runStatus} />
          )}
        </div>
        <LimitsPanel lang={lang} />
      </main>
    </div>
  );
}
