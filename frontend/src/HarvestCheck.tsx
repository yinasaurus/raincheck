import { useEffect, useState } from "react";
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { ChartSwitch } from "./charts";
import { showDeviation, showMm } from "./numbers";
import type { ValidationBody, ValidationYear } from "./types";

const gold = "#D9A21B";
const rain = "#3E91B5";
const ink = "#12303B";

function Dot(props: { cx?: number; cy?: number; payload?: ValidationYear; showYears?: boolean }) {
  const { cx = 0, cy = 0, payload, showYears = false } = props;
  if (!payload) return <g />;
  const ring = payload.below_line;
  return (
    <g>
      <circle cx={cx} cy={cy} r={ring ? 8 : 4} fill={ring ? "none" : rain} stroke={ring ? gold : "none"} strokeWidth={2} />
      {showYears && payload.worst_yield ? (
        <text x={cx + 10} y={cy + 4} fill={ink} fontSize={12}>
          {payload.year}
        </text>
      ) : null}
    </g>
  );
}

function useWideScreen() {
  const [wide, setWide] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(min-width: 768px)");
    const apply = () => setWide(query.matches);
    apply();
    query.addEventListener("change", apply);
    return () => query.removeEventListener("change", apply);
  }, []);
  return wide;
}

export function HarvestCheck({ report }: { report: ValidationBody }) {
  const showYears = useWideScreen();
  const points = (report.series ?? []).filter((row) => row.yield_deviation_pct != null && row.season_rainfall_mm != null);
  const summary = [
    report.headline,
    report.sample_size_warning,
    "The gold line is the payment line at 1,363.0 mm.",
    "Gold rings are the seasons below that line.",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <section className="rounded-2xl border border-line bg-panel p-4" data-testid="harvest-check">
      <h2 className="font-display text-2xl font-bold text-water">Does rainfall match real harvests?</h2>
      <p className="mt-2 text-sm leading-6" data-testid="harvest-headline">
        {report.headline}
      </p>
      <div className="mt-3">
        <ChartSwitch
          lang="en"
          table={
            <div className="max-w-full overflow-x-auto" tabIndex={0}>
              <table className="w-full text-left text-sm">
                <thead>
                  <tr>
                    <th className="py-1 pr-3">Year</th>
                    <th className="py-1 pr-3">Season rainfall</th>
                    <th className="py-1 pr-3">Yield vs trend</th>
                    <th className="py-1 pr-3">Below the line</th>
                    <th className="py-1">Worst harvest</th>
                  </tr>
                </thead>
                <tbody>
                  {(report.series ?? []).map((row) => (
                    <tr key={row.year} className="border-t border-line">
                      <td className="py-1 pr-3">{row.year}</td>
                      <td className="py-1 pr-3">{showMm(row.season_rainfall_mm, "en")}</td>
                      <td className="py-1 pr-3">{showDeviation(row.yield_deviation_pct, "en")}</td>
                      <td className="py-1 pr-3">{row.below_line ? "yes" : "no"}</td>
                      <td className="py-1">{row.worst_yield ? "yes" : "no"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          }
        >
          <div className="h-80" role="img" aria-label={summary}>
            <div className="h-full" inert>
              <ResponsiveContainer width="100%" height="100%">
                <ScatterChart margin={{ top: 16, right: 16, bottom: 16, left: 8 }}>
                  <CartesianGrid stroke="#C3D5DA" />
                  <XAxis dataKey="season_rainfall_mm" type="number" name="Season rainfall" unit=" mm" tick={{ fill: ink, fontSize: 12 }} />
                  <YAxis dataKey="yield_deviation_pct" type="number" name="Yield vs trend" unit="%" tick={{ fill: ink, fontSize: 12 }} width={48} />
                  <Tooltip cursor={{ strokeDasharray: "3 3" }} />
                  <ReferenceLine x={1363} stroke={gold} strokeWidth={2} label={{ value: "Payment line", fill: ink, fontSize: 12, position: "insideTopRight" }} />
                  <Scatter data={points} shape={(props: { cx?: number; cy?: number; payload?: ValidationYear }) => <Dot {...props} showYears={showYears} />} />
                </ScatterChart>
              </ResponsiveContainer>
            </div>
          </div>
        </ChartSwitch>
      </div>
      <p className="mt-3 text-sm leading-6">
        Source: {report.source_name}. Retrieved {report.retrieval_date}.{" "}
        <a className="text-water underline" href={report.source_url}>
          {report.source_url}
        </a>
      </p>
      <p className="mt-2 text-sm leading-6" data-testid="harvest-attribution">
        Credit: Philippine Statistics Authority.{" "}
        <a className="text-water underline" href={report.terms_url || "https://openstat.psa.gov.ph/Terms"}>
          {report.terms_url || "https://openstat.psa.gov.ph/Terms"}
        </a>
        . Yield is production divided by harvested area, rounded to 0.01 tonnes per hectare.
      </p>
      <p className="mt-2 text-sm leading-6">{report.sample_size_warning}</p>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm leading-6">
        {(report.limitations ?? []).slice(1).map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  );
}
