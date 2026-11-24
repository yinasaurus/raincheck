import { t, type Lang } from "./copy";
import { isNumber, showMm } from "./numbers";

const MAX_MM = 2000;
const TOP = 28;
const BOTTOM = 292;
const TUBE_X = 78;
const TUBE_W = 44;

function yOf(mm: number): number {
  const clamped = Math.min(MAX_MM, Math.max(0, mm));
  return BOTTOM - (clamped / MAX_MM) * (BOTTOM - TOP);
}

export function RainGauge({
  soFar,
  usual,
  low,
  high,
  line,
  lang,
}: {
  soFar: number | null;
  usual: number | null;
  low: number | null;
  high: number | null;
  line: number | null;
  lang: Lang;
}) {
  const fillTop = isNumber(soFar) ? yOf(soFar) : BOTTOM;
  const bandTop = isNumber(low) && isNumber(high) ? yOf(Math.max(low, high)) : null;
  const bandBottom = isNumber(low) && isNumber(high) ? yOf(Math.min(low, high)) : null;
  const lineY = isNumber(line) ? yOf(line) : null;
  const usualY = isNumber(usual) ? yOf(usual) : null;
  const label = [
    `${t(lang, "rain")} ${showMm(soFar, lang)}`,
    `${t(lang, "usualNow")} ${showMm(usual, lang)}`,
    `${t(lang, "line")} ${showMm(line, lang)}`,
  ].join(". ");

  return (
    <svg viewBox="0 0 320 320" className="aspect-square h-auto w-full" role="img" aria-label={label}>
      {[0, 500, 1000, 1500, 2000].map((tick) => (
        <g key={tick}>
          <line x1={TUBE_X - 8} x2={TUBE_X} y1={yOf(tick)} y2={yOf(tick)} stroke="#3F5A64" strokeWidth="1" />
          <text x="4" y={yOf(tick) + 4} fill="#3F5A64" fontSize="12" fontFamily="Atkinson Hyperlegible, sans-serif">
            {tick.toLocaleString("en-US")}
          </text>
        </g>
      ))}
      <rect x={TUBE_X} y={TOP} width={TUBE_W} height={BOTTOM - TOP} rx="12" fill="#FBFDFD" stroke="#C3D5DA" />
      {bandTop !== null && bandBottom !== null ? (
        <rect x={TUBE_X + 4} y={bandTop} width={TUBE_W - 8} height={Math.max(bandBottom - bandTop, 1)} fill="#3E91B5" opacity="0.28" />
      ) : null}
      <rect x={TUBE_X + 4} y={fillTop} width={TUBE_W - 8} height={Math.max(BOTTOM - fillTop - 2, 0)} fill="#3E91B5" />
      {usualY !== null ? (
        <line x1={TUBE_X - 4} x2={TUBE_X + TUBE_W + 4} y1={usualY} y2={usualY} stroke="#3F5A64" strokeWidth="2" strokeDasharray="4 3" />
      ) : null}
      {lineY !== null ? (
        <g>
          <line x1={TUBE_X - 6} x2={TUBE_X + TUBE_W + 8} y1={lineY} y2={lineY} stroke="#D9A21B" strokeWidth="3" />
          <text x={TUBE_X + TUBE_W + 14} y={lineY} fill="#D9A21B" fontSize="16" fontFamily="Gabarito, sans-serif">
            <tspan x={TUBE_X + TUBE_W + 14} dy="-4">
              {t(lang, "line")}
            </tspan>
            <tspan x={TUBE_X + TUBE_W + 14} dy="16">
              {showMm(line, lang)}
            </tspan>
          </text>
        </g>
      ) : null}
    </svg>
  );
}

export function SeasonBar({ observed, line }: { observed: number | null; line: number | null }) {
  const fill = isNumber(observed) ? Math.min(100, Math.max(0, (observed / MAX_MM) * 100)) : 0;
  const mark = isNumber(line) ? Math.min(100, Math.max(0, (line / MAX_MM) * 100)) : null;
  return (
    <div className="relative h-4 overflow-hidden rounded-xl bg-line" aria-hidden="true">
      <div className="h-full bg-rain" style={{ width: `${fill}%` }} />
      {mark !== null ? <div className="absolute top-0 h-full w-[3px] bg-gold" style={{ left: `${mark}%` }} /> : null}
    </div>
  );
}
