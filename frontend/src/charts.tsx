import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  ReferenceArea,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  useChartHeight,
  useChartWidth,
  usePlotArea,
  useXAxisScale,
  useYAxisScale,
  XAxis,
  YAxis,
} from "recharts";
import { t, type Lang } from "./copy";
import { formatMm, isNumber, strictlyBelow } from "./numbers";

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
const paper = "#FBFDFD";

const CHAR_PX = 6.4;
const ASCENT = 11;
const DESCENT = 4;
const HALO = 3;

export type PlacedLabel = {
  text: string;
  x: number;
  y: number;
  anchor: "start" | "end";
};

export type LabelBox = {
  left: number;
  top: number;
  right: number;
  bottom: number;
};

type SeasonSpot = { year: number; total: number; cx: number; cy: number };

export function labelBox(label: PlacedLabel): LabelBox {
  const textWidth = label.text.length * CHAR_PX;
  const left = (label.anchor === "start" ? label.x : label.x - textWidth) - HALO;
  return {
    left,
    top: label.y - ASCENT - HALO,
    right: left + textWidth + HALO * 2,
    bottom: label.y + DESCENT + HALO,
  };
}

export function labelBoxesOverlap(a: LabelBox, b: LabelBox): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

function seasonText(point: SeasonSpot): string {
  return `${point.year}: ${Math.round(point.total).toLocaleString("en-US")}`;
}

function mergedText(points: SeasonSpot[]): string {
  const years = points.map((point) => String(point.year)).join(", ");
  const totals = points.map((point) => Math.round(point.total).toLocaleString("en-US")).join(" / ");
  return `${years}: ${totals}`;
}

function candidates(text: string, cx: number, cy: number): PlacedLabel[] {
  const slots = [-46, -18, 28, 52];
  const nudges = [0, 24, 48, 80, 120];
  const placed: PlacedLabel[] = [];
  for (const nudge of nudges) {
    for (const dy of slots) {
      placed.push({ text, x: cx + 12 + nudge, y: cy + dy, anchor: "start" });
      placed.push({ text, x: cx - 12 - nudge, y: cy + dy, anchor: "end" });
    }
  }
  return placed;
}

function fits(label: PlacedLabel, bounds: { width: number; height: number; minLeft: number }, occupied: LabelBox[]): boolean {
  const box = labelBox(label);
  if (box.left < bounds.minLeft || box.top < 1 || box.right > bounds.width - 1 || box.bottom > bounds.height - 1) return false;
  return occupied.every((item) => !labelBoxesOverlap(box, item));
}

function groupsOf(points: SeasonSpot[]): SeasonSpot[][] {
  const sorted = [...points].sort((a, b) => a.year - b.year);
  const groups: SeasonSpot[][] = [];
  for (const point of sorted) {
    const last = groups[groups.length - 1];
    if (last && point.year === last[last.length - 1].year + 1) last.push(point);
    else groups.push([point]);
  }
  return groups;
}

function placeGroup(group: SeasonSpot[], occupied: LabelBox[], bounds: { width: number; height: number; minLeft: number }): PlacedLabel[] {
  if (group.length === 1) {
    const found = candidates(seasonText(group[0]), group[0].cx, group[0].cy).find((item) => fits(item, bounds, occupied));
    if (found) return [found];
  } else if (group.length === 2) {
    const first = candidates(seasonText(group[0]), group[0].cx, group[0].cy);
    const second = candidates(seasonText(group[1]), group[1].cx, group[1].cy);
    for (const left of first) {
      if (!fits(left, bounds, occupied)) continue;
      const leftBox = labelBox(left);
      for (const right of second) {
        if (labelBoxesOverlap(leftBox, labelBox(right))) continue;
        if (fits(right, bounds, occupied)) return [left, right];
      }
    }
  } else {
    const placed: PlacedLabel[] = [];
    const local = [...occupied];
    let open = true;
    for (const point of group) {
      const found = candidates(seasonText(point), point.cx, point.cy).find((item) => fits(item, bounds, local));
      if (!found) {
        open = false;
        break;
      }
      placed.push(found);
      local.push(labelBox(found));
    }
    if (open) return placed;
  }
  const text = mergedText(group);
  const anchor = group[Math.floor((group.length - 1) / 2)];
  const found = candidates(text, anchor.cx, anchor.cy).find((item) => fits(item, bounds, occupied));
  if (found) return [found];
  const low = group.reduce((best, point) => (point.cy > best.cy ? point : best));
  return [{ text, x: bounds.minLeft + 4, y: Math.min(bounds.height - 8, low.cy + 52), anchor: "start" }];
}

export function placeSeasonLabels(
  points: SeasonSpot[],
  payment: PlacedLabel,
  bounds: { width: number; height: number; minLeft: number },
): PlacedLabel[] {
  const occupied = [labelBox(payment)];
  const placed: PlacedLabel[] = [];
  for (const group of groupsOf(points)) {
    const next = placeGroup(group, occupied, bounds);
    placed.push(...next);
    occupied.push(...next.map(labelBox));
  }
  return placed;
}

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
  width,
}: {
  totals: { year: number; season_total_mm: number }[];
  rolling: { end_year: number; mean_mm: number }[];
  line: number | null;
  lang: Lang;
  animate: boolean;
  width?: number;
}) {
  const roll = new Map(rolling.map((row) => [row.end_year, row.mean_mm]));
  const points = totals.map((row) => ({
    year: row.year,
    total: row.season_total_mm,
    rolling: row.year >= 2010 ? (roll.get(row.year) ?? null) : null,
    below: isNumber(line) && strictlyBelow(row.season_total_mm, line),
  }));
  const frame = useRef<HTMLDivElement>(null);
  const [frameWidth, setFrameWidth] = useState(width ?? 800);
  const narrow = frameWidth < 560;
  useEffect(() => {
    if (width) {
      setFrameWidth(width);
      return;
    }
    const node = frame.current;
    if (!node) return;
    const measure = () => setFrameWidth(node.clientWidth);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [width]);
  const years = points.map((row) => row.year);
  const crowdedEnd = years.length % 2 === 0;
  const xTicks = years.filter((_year, index) => {
    if (narrow && crowdedEnd && index === years.length - 2) return false;
    return index % 2 === 0 || index === years.length - 1;
  });
  const highest = Math.max(0, ...points.map((row) => row.total), isNumber(line) ? line : 0);
  const yTicks = [0, 500, 1000, 1500, 2000];
  if (highest > 2000) yTicks.push(2500);
  const belowYears = new Set(points.filter((row) => row.below).map((row) => row.year));
  const lineText = isNumber(line) ? `${t(lang, "line")} ${formatMm(line)}` : "";
  const summary = [
    t(lang, "trend"),
    lineText,
    `${t(lang, "total")}, ${t(lang, "rolling")}`,
    ...[...belowYears].map((year) => {
      const row = points.find((item) => item.year === year);
      return row ? `${year}: ${Math.round(row.total).toLocaleString("en-US")}` : "";
    }),
  ]
    .filter(Boolean)
    .join(". ");

  return (
    <div>
      <div className="h-80" role="img" aria-label={summary} ref={frame}>
        <div className="h-full" aria-hidden="true">
        <ResponsiveContainer width={width ?? "100%"} height={width ? 320 : "100%"}>
          <ComposedChart data={points} margin={{ top: 36, right: narrow ? 8 : 40, left: 8, bottom: 4 }}>
            <CartesianGrid stroke="#C3D5DA" vertical={false} />
            <XAxis
              dataKey="year"
              ticks={xTicks}
              interval={0}
              height={narrow ? 52 : 28}
              tick={(props) => {
                const value = props.payload?.value as number | undefined;
                const x = Number(props.x ?? 0);
                const y = Number(props.y ?? 0) + 14;
                const shift = !narrow && crowdedEnd && value === years[years.length - 1];
                return (
                  <text
                    x={x}
                    y={y}
                    textAnchor={shift ? "start" : narrow ? "end" : "middle"}
                    fill={ink}
                    fontSize={13}
                    fontFamily="Atkinson Hyperlegible, sans-serif"
                    transform={narrow ? `rotate(-60 ${x} ${y})` : undefined}
                  >
                    {value}
                  </text>
                );
              }}
            />
            <YAxis
              ticks={yTicks}
              domain={[0, yTicks[yTicks.length - 1]]}
              tickFormatter={(value: number) => value.toLocaleString("en-US")}
              tick={{ fill: ink, fontSize: 13, fontFamily: "Atkinson Hyperlegible, sans-serif" }}
              width={72}
              label={{
                value: t(lang, "mmSeason"),
                angle: -90,
                position: "insideLeft",
                fill: ink,
                fontSize: 13,
                style: { textAnchor: "middle" },
              }}
            />
            {isNumber(line) ? (
              <ReferenceArea y1={0} y2={line} fill={gold} fillOpacity={0.12} strokeOpacity={0} ifOverflow="hidden" />
            ) : null}
            <Line
              type="linear"
              dataKey="rolling"
              stroke={stone}
              strokeWidth={1}
              strokeDasharray="4 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={animate}
              legendType="none"
            />
            <Line
              type="linear"
              dataKey="total"
              stroke={rain}
              strokeWidth={2}
              dot={(props) => <SeasonDot {...props} belowYears={belowYears} />}
              activeDot={false}
              isAnimationActive={animate}
              legendType="none"
            />
            {isNumber(line) ? (
              <ReferenceLine y={line} stroke={gold} strokeWidth={2} label={<LineTag text={lineText} />} />
            ) : null}
            {isNumber(line) ? <SeasonLabels points={points} line={line} lineText={lineText} /> : null}
          </ComposedChart>
        </ResponsiveContainer>
        </div>
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-sm" style={{ color: ink }}>
        <li className="flex items-center gap-2">
          <svg width="28" height="10" aria-hidden="true">
            <line x1="0" y1="5" x2="28" y2="5" stroke={rain} strokeWidth="2" />
          </svg>
          {t(lang, "total")}
        </li>
        <li className="flex items-center gap-2">
          <svg width="28" height="10" aria-hidden="true">
            <line x1="0" y1="5" x2="28" y2="5" stroke={stone} strokeWidth="1" strokeDasharray="4 3" />
          </svg>
          {t(lang, "rolling")}
        </li>
        <li className="flex items-center gap-2">
          <svg width="16" height="16" aria-hidden="true">
            <circle cx="8" cy="8" r="5.5" fill={paper} stroke={gold} strokeWidth="2.5" />
          </svg>
          {t(lang, "belowRing")}
        </li>
      </ul>
    </div>
  );
}

function SeasonDot({
  cx,
  cy,
  payload,
  belowYears,
}: {
  cx?: number;
  cy?: number;
  payload?: { year: number };
  belowYears: Set<number>;
}) {
  if (cx == null || cy == null || !payload) return null;
  const below = belowYears.has(payload.year);
  if (!below) return <circle cx={cx} cy={cy} r={3.5} fill={rain} />;
  return <circle cx={cx} cy={cy} r={6.5} fill={paper} stroke={gold} strokeWidth={2.5} />;
}

function SeasonLabels({
  points,
  line,
  lineText,
}: {
  points: { year: number; total: number; below: boolean }[];
  line: number;
  lineText: string;
}) {
  const xScale = useXAxisScale();
  const yScale = useYAxisScale();
  const plot = usePlotArea();
  const chartWidth = useChartWidth();
  const chartHeight = useChartHeight();
  if (!xScale || !yScale || !plot || !chartWidth || !chartHeight) return null;
  const spots = points.flatMap((point) => {
    if (!point.below) return [];
    const cx = Number(xScale(point.year));
    const cy = Number(yScale(point.total));
    if (!Number.isFinite(cx) || !Number.isFinite(cy)) return [];
    return [{ year: point.year, total: point.total, cx, cy }];
  });
  const lineY = Number(yScale(line));
  if (!Number.isFinite(lineY)) return null;
  const labels = placeSeasonLabels(
    spots,
    { text: lineText, x: plot.x + plot.width, y: lineY - 20, anchor: "end" },
    { width: chartWidth, height: chartHeight, minLeft: plot.x },
  );
  return (
    <g>
      {labels.map((label) => (
        <text
          key={label.text}
          data-label="season"
          x={label.x}
          y={label.y}
          textAnchor={label.anchor}
          fill={ink}
          fontSize={13}
          fontFamily="Atkinson Hyperlegible, sans-serif"
          stroke={paper}
          strokeWidth={5}
          paintOrder="stroke fill"
        >
          {label.text}
        </text>
      ))}
    </g>
  );
}

function LineTag({ viewBox, text }: { viewBox?: { x?: number; y?: number; width?: number }; text?: string }) {
  const x = (viewBox?.x ?? 0) + (viewBox?.width ?? 0);
  const y = (viewBox?.y ?? 0) - 20;
  return (
    <text
      x={x}
      y={y}
      data-label="payment"
      textAnchor="end"
      fill={ink}
      fontSize={13}
      fontFamily="Atkinson Hyperlegible, sans-serif"
      stroke={paper}
      strokeWidth={5}
      paintOrder="stroke fill"
    >
      {text}
    </text>
  );
}
