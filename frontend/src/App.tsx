import { useEffect, useState } from "react";
import { ApiError, getBacktest, getDemoYears, getRegion, getRisk, runDemo } from "./api";
import { t, type Lang } from "./copy";
import { FarmerView } from "./FarmerView";
import { LenderView } from "./LenderView";
import { LimitsPanel } from "./LimitsPanel";
import type { BacktestBody, DemoRun, DemoYear, RegionBody, RiskBody } from "./types";

type Audience = "farmer" | "lender";

export default function App() {
  const [lang, setLang] = useState<Lang>("en");
  const [audience, setAudience] = useState<Audience>("farmer");
  const [years, setYears] = useState<DemoYear[]>([]);
  const [region, setRegion] = useState<RegionBody | null>(null);
  const [backtest, setBacktest] = useState<BacktestBody | null>(null);
  const [risk, setRisk] = useState<RiskBody | null>(null);
  const [loadStatus, setLoadStatus] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [demo, setDemo] = useState<DemoRun | null>(null);
  const [running, setRunning] = useState(false);
  const [runStatus, setRunStatus] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([getDemoYears(), getRegion(), getBacktest(), getRisk()]).then((results) => {
      if (cancelled) return;
      const [yearResult, regionResult, backtestResult, riskResult] = results;
      if (yearResult.status === "fulfilled") {
        setYears(yearResult.value.years);
        setSelectedYear(yearResult.value.years[0]?.year ?? null);
      }
      if (regionResult.status === "fulfilled") setRegion(regionResult.value);
      if (backtestResult.status === "fulfilled") setBacktest(backtestResult.value);
      if (riskResult.status === "fulfilled") setRisk(riskResult.value);
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

  return (
    <div className="min-h-screen overflow-x-hidden bg-paper text-ink">
      <header className="border-b border-stone-300 bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-4">
          <div className="mr-auto">
            <p className="font-serif text-2xl">{t(lang, "name")}</p>
            <p className="text-sm text-stone-700">{place}</p>
          </div>
          <div className="flex rounded-full border border-stone-300 p-1" role="group" aria-label={t(lang, "farmer")}>
            <button type="button" onClick={() => setAudience("farmer")} className={`rounded-full px-3 py-1 text-sm ${audience === "farmer" ? "bg-field text-white" : ""}`}>
              {t(lang, "farmer")}
            </button>
            <button type="button" onClick={() => setAudience("lender")} className={`rounded-full px-3 py-1 text-sm ${audience === "lender" ? "bg-ink text-white" : ""}`}>
              {t(lang, "lender")}
            </button>
          </div>
          <div className="flex rounded-full border border-stone-300 p-1">
            <button type="button" onClick={() => setLang("en")} className={`rounded-full px-3 py-1 text-sm ${lang === "en" ? "bg-stone-200" : ""}`}>
              {t(lang, "english")}
            </button>
            <button type="button" onClick={() => setLang("fil")} className={`rounded-full px-3 py-1 text-sm ${lang === "fil" ? "bg-stone-200" : ""}`}>
              {t(lang, "filipino")}
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0">
          {loadStatus === 503 ? (
            <p role="alert" className="mb-3 text-sm text-clay">
              {t(lang, "down")}
            </p>
          ) : null}
          {loading ? (
            <div aria-busy="true" aria-label={t(lang, "loading")} className="space-y-3">
              <div className="h-24 animate-pulse rounded-2xl bg-stone-200" />
              <div className="h-24 animate-pulse rounded-2xl bg-stone-200" />
              <div className="h-24 animate-pulse rounded-2xl bg-stone-200" />
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
              risk={risk}
              paymentLine={paymentLine}
              onOpenRecord={() => setAudience("lender")}
            />
          ) : (
            <LenderView lang={lang} demo={demo} backtest={backtest} runStatus={runStatus} />
          )}
        </div>
        <LimitsPanel lang={lang} />
      </main>
    </div>
  );
}
