import { readFileSync } from "node:fs";
import path from "node:path";
import { cleanup, render, screen, within } from "@testing-library/react";
import { fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { labelBox, labelBoxesOverlap, TrendChart, type PlacedLabel } from "./charts";
import { en } from "./copy.en";
import { fil } from "./copy.fil";
import { FarmerView } from "./FarmerView";
import { LimitsPanel } from "./LimitsPanel";
import { BANNED_WORDS, firstChanged, formatAmount, formatMm, formatPercent, reducedWindow, reliefSentence, showDeviation, strictlyBelow, withoutRawProbability } from "./numbers";
import { statusMessage } from "./status";
import type { DemoRun } from "./types";

describe("numbers", () => {
  it("shows the yield gap from the trend, and n/a when the harvest is missing", () => {
    expect(showDeviation(12, "en")).toBe("+12%");
    expect(showDeviation(-25, "en")).toBe("-25%");
    expect(showDeviation(0, "en")).toBe("0%");
    expect(showDeviation(null, "en")).toBe(en.na);
  });

  it("formats millimetres, percents, and amounts", () => {
    expect(formatMm(1363)).toBe("1,363.0 mm");
    expect(formatMm(1243.9)).toBe("1,243.9 mm");
    expect(formatPercent(0.08)).toBe("8%");
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatAmount(470735)).toBe("4,707.35");
    expect(formatAmount(329514)).toBe("3,295.14");
    expect(formatAmount(11297634)).toBe("112,976.34");
    expect(formatAmount(11343680)).toBe("113,436.80");
    expect(formatAmount(46046)).toBe("460.46");
  });

  it("treats the payment line as strictly below", () => {
    expect(strictlyBelow(1362.9, 1363)).toBe(true);
    expect(strictlyBelow(1363, 1363)).toBe(false);
    expect(strictlyBelow(1363.1, 1363)).toBe(false);
  });

  it("reads the first changed payment and the relief window", () => {
    const before = [row(4, 470735), row(5, 470735), row(6, 470735)];
    const after = [row(4, 329514, "reduced 30%"), row(5, 329514, "reduced 30%"), row(6, 329514, "reduced 30%")];
    expect(firstChanged(before, after)).toEqual({ month: 4, before: 470735, after: 329514 });
    expect(reducedWindow(after)).toEqual({ count: 3, percent: 30 });
    expect(reliefSentence("en", 3, 30)).toBe("Your next 3 payments are 30% lower.");
  });
});

const reliefModel = JSON.parse(readFileSync(path.resolve("..", "backend", "models", "relief_loo.json"), "utf8")) as {
  payment_line_mm: number;
  trend: { season_totals_mm: { year: number; season_total_mm: number }[] };
};

describe("season rainfall labels", () => {
  it("keeps label boxes apart at 375px and 1280px", () => {
    for (const width of [375, 1280]) {
      const view = render(
        <TrendChart
          lang="en"
          animate={false}
          width={width}
          line={reliefModel.payment_line_mm}
          totals={reliefModel.trend.season_totals_mm}
          rolling={[]}
        />,
      );
      const labels = [...view.container.querySelectorAll("text[data-label]")].map((node) => {
        const text = node.textContent ?? "";
        const placed: PlacedLabel = {
          text,
          x: Number(node.getAttribute("x")),
          y: Number(node.getAttribute("y")),
          anchor: node.getAttribute("text-anchor") === "end" ? "end" : "start",
        };
        return { text, box: labelBox(placed) };
      });
      const joined = labels.map((label) => label.text).join(" ");
      expect(joined).toContain("2003");
      expect(joined).toContain("2004");
      expect(joined).toContain("2017");
      expect(joined).toContain("1,235");
      expect(joined).toContain("1,244");
      expect(joined).toContain("1,239");
      expect(joined).toContain("Payment line 1,363.0 mm");
      for (let i = 0; i < labels.length; i++) {
        for (let j = i + 1; j < labels.length; j++) {
          expect(
            labelBoxesOverlap(labels[i].box, labels[j].box),
            `${width}px: "${labels[i].text}" overlaps "${labels[j].text}"`,
          ).toBe(false);
        }
      }
      view.unmount();
    }
  });
});

describe("copy", () => {
  it("uses the same keys in English and Filipino", () => {
    expect(Object.keys(fil).sort()).toEqual(Object.keys(en).sort());
  });
});

describe("farmer view", () => {
  it("shows the relief banner and keeps forbidden words out of English and Filipino", () => {
    for (const lang of ["en", "fil"] as const) {
      const view = render(
        <>
          <FarmerView {...props(lang, true)} />
          <LimitsPanel lang={lang} />
        </>,
      );
      fireEvent.change(screen.getByRole("slider", { name: lang === "fil" ? "Linggo" : "Week" }), { target: { value: "21" } });
      const text = view.container.textContent ?? "";
      expect(text).toMatch(lang === "fil" ? /30%/ : /Your next 3 payments are 30% lower/);
      expect(text).toMatch(/4,707\.35/);
      expect(text).toMatch(/3,295\.14/);
      expect(text).toMatch(/112,976\.34/);
      expect(text).toMatch(/113,436\.80/);
      expect(text).toMatch(/460\.46/);
      expect(text).not.toMatch(/2000-/);
      expect(BANNED_WORDS.test(text)).toBe(false);
      view.unmount();
    }
  });

  it("shows the no-relief banner", () => {
    render(<FarmerView {...props("en", false)} />);
    fireEvent.change(screen.getByRole("slider", { name: "Week" }), { target: { value: "21" } });
    expect(screen.getByTestId("season-banner").textContent).toContain(
      "No relief this season: rainfall was above the payment line.",
    );
    expect(screen.getByTestId("season-banner").textContent).toContain(
      "Relief depends only on the final measured rainfall, not on the estimate.",
    );
  });

  it("shows one chance, defaults the slider to the season total, and keeps the status block out", () => {
    cleanup();
    for (const lang of ["en", "fil"] as const) {
      const view = render(<FarmerView {...props(lang, true)} />);
      const root = within(view.container);
      fireEvent.change(root.getByRole("slider", { name: lang === "fil" ? "Linggo" : "Week" }), { target: { value: "21" } });
      const text = view.container.textContent ?? "";
      expect(text).not.toContain(lang === "fil" ? "Awtomatikong tuntunin" : "Automatic rule");
      expect(text).not.toMatch(/\d\.\d{4}/);
      expect(text).toContain(lang === "fil" ? "Tsansa ng relief" : "Chance of relief");
      expect(root.queryByRole("heading", { name: /Latest season|Current season|Where this year stands|Pinakabagong season|Katayuan ng kasalukuyang/ })).toBeNull();
      const replay = view.container.querySelector("[data-testid='replay']");
      expect(replay).not.toBeNull();
      expect(view.container.innerHTML.indexOf("data-testid=\"replay\"")).toBeGreaterThan(-1);
      expect(text.indexOf("2004")).toBeLessThan(text.indexOf(lang === "fil" ? "Subukan ang ibang kabuuang ulan" : "Try a different season total"));
      const rainfall = root.getByRole("slider", { name: lang === "fil" ? "Kabuuang ulan sa katapusan ng season" : "End-of-season rainfall" }) as HTMLInputElement;
      expect(rainfall.value).toBe("1243.9");
      const banner = root.getByTestId("season-banner").textContent ?? "";
      const whatIf = root.getByTestId("what-if").textContent ?? "";
      expect(banner).toContain(lang === "fil" ? "30%" : "Your next 3 payments are 30% lower.");
      expect(whatIf).toContain(lang === "fil" ? "30%" : "Your next 3 payments are 30% lower.");
      view.unmount();
    }
    expect(withoutRawProbability("The chance is 0.9600. Rainfall is 90.0% of normal.")).toBe("Rainfall is 90.0% of normal.");
  });

  it("shows the record-service message on 503 and plain words on 409", () => {
    const down = render(<FarmerView {...props("en", false)} runStatus={503} />);
    expect(down.container.textContent).toContain("The record service is not running");
    expect(down.container.textContent).toContain(".\\scripts\\dev.ps1");
    expect(statusMessage(409, "en")).toContain("conflicts with a record that already exists");
    down.unmount();
  });
});

function row(month: number, payment_cents: number, note = ""): { month: number; payment_cents: number; note?: string } {
  return { month, payment_cents, note };
}

function props(lang: "en" | "fil", relief: boolean) {
  const scheduleBefore = [row(1, 470735), row(4, 470735), row(5, 470735), row(6, 470735)];
  const scheduleAfter = relief
    ? [row(1, 470735), row(4, 329514, "reduced 30%"), row(5, 329514, "reduced 30%"), row(6, 329514, "reduced 30%")]
    : scheduleBefore;
  const demo: DemoRun = {
    year: relief ? 2004 : 2020,
    weekly: [
      {
        week_index: 21,
        cumulative_rainfall_mm: relief ? 1243.9 : 1653.8,
        rain_pct_of_normal: 0.9,
        p_relief: relief ? 0.96 : 0.12,
        rule_score: 0.5,
        projected_total_mm: { p10: 1200, p50: 1400, p90: 1600 },
        explanations: {
          en: "By week 21, rainfall so far is 90.0% of normal. The chance the season total ends below the 1363.0 mm payment line is 0.9600. This score is advisory.",
          fil: "Sa ika-21 na linggo, ang ulan sa ngayon ay 90.0% ng normal. Ang posibilidad ay 0.9600. Payo lamang ang markang ito.",
        },
      },
    ],
    rainfall_line: {
      trigger_rainfall_mm: 1363,
      observed_rainfall_mm: relief ? 1243.9 : 1653.8,
      fired: relief,
    },
    loan: { principal_cents: 10_000_000, annual_rate_bps: 1200, term_months: 24 },
    schedule_before: scheduleBefore,
    schedule_after: scheduleAfter,
    summary: {
      baseline_total_paid_cents: 11297634,
      relief_total_paid_cents: relief ? 11343680 : 11297634,
      extra_cost_cents: relief ? 46046 : 0,
      baseline_months: 24,
      relief_months: 24,
    },
  };
  return {
    lang,
    years: [
      { year: 2004, role: "relief", p_relief_by_week: [] },
      { year: 2017, role: "relief", p_relief_by_week: [] },
      { year: 2020, role: "model false alarm, no relief", p_relief_by_week: [] },
    ],
    selectedYear: demo.year,
    onSelect: () => undefined,
    onRun: () => undefined,
    running: false,
    runStatus: null as number | null,
    demo,
    seasonTotal: relief ? 1243.9 : 1653.8,
    paymentLine: 1363,
    onOpenRecord: () => undefined,
  };
}
