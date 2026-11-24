import { useState, type ReactNode } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { t, type Lang } from "./copy";
import { isNumber } from "./numbers";

export function ChartSwitch({
  lang,
  table,
  children,
}: {
  lang: Lang;
  table: ReactNode;
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  return (
    <div>
      <button
        type="button"
        aria-pressed={asTable}
        onClick={() => setAsTable((value) => !value)}
        className="mb-2 min-h-11 rounded-xl border border-water px-3 text-sm text-water"
      >
        {asTable ? t(lang, "viewChart") : t(lang, "viewTable")}
      </button>
      {asTable ? table : children}
    </div>
  );
}

const ink = "#12303B";
const rain = "#3E91B5";
const gold = "#D9A21B";
const stone = "#3F5A64";

interface RainPoint {
  week: number;
  soFar: number | null;
  normal: number | null;
}

interface FanPoint {
  week: number;
  p10: number | null;
  span: number | null;
  p50: number | null;
  p90: number | null;
}

export function RainChart({ points, lang, animate }: { points: RainPoint[]; lang: Lang; animate: boolean }) {
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#e6e0d4" vertical={false} />
          <XAxis dataKey="week" tick={{ fill: ink, fontSize: 12 }} />
          <YAxis tick={{ fill: ink, fontSize: 12 }} width={48} unit="" />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="soFar" name={t(lang, "rain")} stroke={rain} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={animate} />
          <Line type="monotone" dataKey="normal" name={t(lang, "normal")} stroke={stone} strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={animate} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function FanChart({
  points,
  line,
  lang,
  animate,
}: {
  points: FanPoint[];
  line: number | null;
  lang: Lang;
  animate: boolean;
}) {
  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#e6e0d4" vertical={false} />
          <XAxis dataKey="week" tick={{ fill: ink, fontSize: 12 }} />
          <YAxis tick={{ fill: ink, fontSize: 12 }} width={48} />
          <Tooltip />
          <Legend />
          <Area dataKey="p10" name={t(lang, "low")} stackId="fan" stroke="none" fill="transparent" legendType="none" />
          <Area dataKey="span" name={`${t(lang, "low")}–${t(lang, "high")}`} stackId="fan" stroke="none" fill={rain} fillOpacity={0.18} />
          <Line type="monotone" dataKey="p50" name={t(lang, "mid")} stroke={rain} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={animate} />
          <Line type="monotone" dataKey="p90" name={t(lang, "high")} stroke={rain} strokeDasharray="4 4" dot={false} connectNulls={false} isAnimationActive={animate} />
          {isNumber(line) ? <ReferenceLine y={line} stroke={gold} strokeWidth={1.5} label={t(lang, "line")} /> : null}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function PaymentChart({
  before,
  after,
  lang,
  animate,
}: {
  before: { month: number; payment: number }[];
  after: { month: number; payment: number }[];
  lang: Lang;
  animate: boolean;
}) {
  const rows = before.map((row, index) => ({
    month: row.month,
    before: row.payment,
    after: after[index]?.payment ?? null,
  }));
  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#e6e0d4" vertical={false} />
          <XAxis dataKey="month" tick={{ fill: ink, fontSize: 12 }} />
          <YAxis tick={{ fill: ink, fontSize: 12 }} width={56} />
          <Tooltip />
          <Legend />
          <Line type="stepAfter" dataKey="before" name={t(lang, "before")} stroke={stone} strokeDasharray="5 4" dot={false} isAnimationActive={animate} />
          <Line type="stepAfter" dataKey="after" name={t(lang, "after")} stroke={rain} dot={false} isAnimationActive={animate} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export function TrendChart({
  totals,
  rolling,
  line,
  lang,
  animate,
}: {
  totals: { year: number; season_total_mm: number }[];
  rolling: { end_year: number; mean_mm: number }[];
  line: number | null;
  lang: Lang;
  animate: boolean;
}) {
  const roll = new Map(rolling.map((row) => [row.end_year, row.mean_mm]));
  const points = totals.map((row) => ({
    year: row.year,
    total: row.season_total_mm,
    rolling: roll.get(row.year) ?? null,
  }));
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#e5e7eb" vertical={false} />
          <XAxis dataKey="year" tick={{ fill: ink, fontSize: 11 }} />
          <YAxis tick={{ fill: ink, fontSize: 12 }} width={48} />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="total" name={t(lang, "total")} stroke={rain} dot={false} isAnimationActive={animate} />
          <Line type="monotone" dataKey="rolling" name={t(lang, "rolling")} stroke={stone} strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={animate} />
          {isNumber(line) ? <ReferenceLine y={line} stroke={gold} label={t(lang, "line")} /> : null}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
